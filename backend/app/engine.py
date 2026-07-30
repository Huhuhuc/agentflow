import json
import re
import time
from collections import defaultdict, deque
from typing import Any

from sqlalchemy.orm import Session

from .models import Execution, ExecutionLog


class GraphError(ValueError):
    pass


def validate_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    ids = [node.get("id") for node in nodes]
    if not nodes:
        return ["Workflow must contain at least one node"]
    if len(ids) != len(set(ids)):
        errors.append("Node IDs must be unique")
    known = set(ids)
    for edge in edges:
        if edge.get("source") not in known or edge.get("target") not in known:
            errors.append("Every edge must reference existing nodes")
    try:
        topological_order(graph)
    except GraphError as exc:
        errors.append(str(exc))
    triggers = [node for node in nodes if node.get("type") == "trigger"]
    if len(triggers) != 1:
        errors.append("Workflow must contain exactly one trigger")
    return list(dict.fromkeys(errors))


def topological_order(graph: dict[str, Any]) -> list[str]:
    nodes = {node["id"] for node in graph.get("nodes", [])}
    indegree = {node_id: 0 for node_id in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges", []):
        source, target = edge.get("source"), edge.get("target")
        if source in nodes and target in nodes:
            outgoing[source].append(target)
            indegree[target] += 1
    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for target in outgoing[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(ordered) != len(nodes):
        raise GraphError("Workflow graph cannot contain cycles")
    return ordered


TOKEN_PATTERN = re.compile(r"\{\{\s*([^}]+)\s*\}\}")


def resolve(value: Any, context: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    def replace(match: re.Match) -> str:
        current: Any = context
        for part in match.group(1).strip().split("."):
            current = current.get(part, "") if isinstance(current, dict) else ""
        return json.dumps(current, ensure_ascii=False) if isinstance(current, (dict, list)) else str(current)
    return TOKEN_PATTERN.sub(replace, value)


def run_node(node: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], int]:
    node_type = node.get("type")
    config = node.get("data", {}).get("config", {})
    if node_type == "trigger":
        return context.get("trigger", {}), 0
    if node_type == "agent":
        source = json.dumps(context, ensure_ascii=False).lower()
        category = "complaint" if any(word in source for word in ["投诉", "退款", "complaint", "angry"]) else "inquiry"
        confidence = 0.72 if category == "complaint" else 0.94
        return {"category": category, "confidence": confidence, "text": "已根据知识库生成处理建议。", "model": config.get("model", "mock-agent")}, 168
    if node_type == "condition":
        field = config.get("field", "")
        expected = config.get("value")
        current: Any = context
        for part in field.split("."):
            current = current.get(part) if isinstance(current, dict) else None
        return {"matched": current == expected, "value": current}, 0
    if node_type == "http":
        return {"status": 200, "url": resolve(config.get("url", "https://example.test"), context), "mock": True}, 0
    if node_type == "notification":
        return {"sent": True, "channel": config.get("channel", "manual-review"), "message": resolve(config.get("message", "需要人工处理"), context)}, 0
    if node_type == "output":
        return {"result": resolve(config.get("template", "{{trigger}}"), context)}, 0
    raise GraphError(f"Unsupported node type: {node_type}")


def execute_graph(db: Session, execution: Execution, graph: dict[str, Any]) -> Execution:
    errors = validate_graph(graph)
    if errors:
        execution.status = "failed"
        execution.error_message = "; ".join(errors)
        db.commit()
        return execution
    start = time.perf_counter()
    execution.status = "running"
    db.commit()
    nodes = {node["id"]: node for node in graph["nodes"]}
    incoming_labels: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        incoming_labels[edge["target"]].append(edge)
    context: dict[str, Any] = {"trigger": execution.input_data}
    try:
        for node_id in topological_order(graph):
            node = nodes[node_id]
            should_skip = False
            for edge in incoming_labels[node_id]:
                source_result = context.get(edge["source"], {})
                label = edge.get("label")
                if label == "true" and not source_result.get("matched"):
                    should_skip = True
                if label == "false" and source_result.get("matched"):
                    should_skip = True
            status = "skipped" if should_skip else "success"
            node_start = time.perf_counter()
            output, tokens = ({}, 0) if should_skip else run_node(node, context)
            if not should_skip:
                context[node_id] = output
            log = ExecutionLog(
                execution_id=execution.id,
                node_id=node_id,
                node_name=node.get("data", {}).get("label", node_id),
                node_type=node.get("type", "unknown"),
                status=status,
                input_data=context.get("trigger", {}),
                output_data=output,
                duration_ms=int((time.perf_counter() - node_start) * 1000),
                token_used=tokens,
            )
            db.add(log)
            execution.token_used += tokens
        terminal = graph.get("nodes", [])[-1]["id"]
        execution.output_data = context.get(terminal, context)
        execution.status = "success"
        execution.cost = round(execution.token_used * 0.000002, 6)
    except Exception as exc:
        execution.status = "failed"
        execution.error_message = str(exc)
    execution.duration_ms = int((time.perf_counter() - start) * 1000)
    db.commit()
    db.refresh(execution)
    return execution

