import json
import re
import time
from collections import defaultdict, deque
from typing import Any

from sqlalchemy.orm import Session

from .llm import call_llm
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


def terminal_node_ids(graph: dict[str, Any]) -> list[str]:
    """返回图中所有无出边的节点（真正的终点），按节点声明顺序。

    不依赖 nodes 数组的排列顺序，因此新增节点或调整顺序都不会改变结果。
    """
    node_ids = [node["id"] for node in graph.get("nodes", [])]
    known = set(node_ids)
    with_outgoing = {
        edge.get("source")
        for edge in graph.get("edges", [])
        if edge.get("source") in known and edge.get("target") in known
    }
    return [node_id for node_id in node_ids if node_id not in with_outgoing]


def pick_terminal(graph: dict[str, Any], order: list[str], executed: list[str]) -> str | None:
    """在实际执行到的节点中挑选代表最终结果的节点。

    优先级：已执行的 output 节点 > 已执行的无出边节点 > 最后一个已执行节点。
    条件分支导致部分终点被跳过时，仍能取到真正走通的那条分支的结果。
    """
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    executed_set = set(executed)
    terminals = set(terminal_node_ids(graph))
    reached = [node_id for node_id in order if node_id in terminals and node_id in executed_set]
    outputs = [node_id for node_id in reached if nodes.get(node_id, {}).get("type") == "output"]
    chosen = outputs or reached
    if chosen:
        return chosen[-1]
    ran = [node_id for node_id in order if node_id in executed_set]
    return ran[-1] if ran else None


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
        return call_llm(config, context)
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
    executed: list[str] = []
    order = topological_order(graph)
    try:
        for node_id in order:
            node = nodes[node_id]
            incoming = incoming_labels[node_id]
            active_edges = [edge for edge in incoming if edge["source"] in context and
                            (edge.get("label") not in {"true", "false"} or
                             bool(context[edge["source"]].get("matched")) == (edge["label"] == "true"))]
            should_skip = bool(incoming) and not active_edges
            status = "skipped" if should_skip else "success"
            node_start = time.perf_counter()
            try:
                output, tokens = ({}, 0) if should_skip else run_node(node, context)
            except Exception as exc:
                db.add(ExecutionLog(execution_id=execution.id, node_id=node_id,
                    node_name=node.get("data", {}).get("label", node_id), node_type=node.get("type", "unknown"),
                    status="failed", input_data=context.get("trigger", {}), output_data={},
                    duration_ms=int((time.perf_counter() - node_start) * 1000), error_message=str(exc)))
                db.commit()
                raise
            if not should_skip:
                context[node_id] = output
                executed.append(node_id)
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
            db.commit()
        terminal = pick_terminal(graph, order, executed)
        execution.output_data = context.get(terminal, context) if terminal else context
        execution.status = "success"
        execution.cost = round(execution.token_used * 0.000002, 6)
    except Exception as exc:
        execution.status = "failed"
        execution.error_message = str(exc)
    execution.duration_ms = int((time.perf_counter() - start) * 1000)
    db.commit()
    db.refresh(execution)
    return execution

