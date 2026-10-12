import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_runtime import make_snapshot, real_turn, run_agent
from app.agent_tools import invoke_tool
from app.auth import create_token, hash_password
from app.config import settings
from app.database import Base, get_db
from app.models import AgentFeedback, AgentRun, AgentTicket, Execution, ExecutionLog, Tenant, User, Workflow, WorkflowRunSnapshot, WorkflowVersion


@pytest.fixture
def store():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        tenant = Tenant(name="Test tenant"); db.add(tenant); db.flush()
        user = User(tenant_id=tenant.id, email="agent@test.dev", name="Tester", password_hash=hash_password("test1234"))
        feedback = AgentFeedback(tenant_id=tenant.id, text="更新后火球技能伤害异常", version="2.4")
        db.add_all([user, feedback]); db.commit()
        yield db, factory, user, feedback
    engine.dispose()


def new_run(db, user, feedback, mode="mock"):
    run = AgentRun(tenant_id=user.tenant_id, feedback_id=feedback.id, snapshot=make_snapshot(feedback.text, feedback.version, mode))
    db.add(run); db.commit()
    return run


def test_agent_tools_and_draft_require_confirmation(store):
    db, _, user, feedback = store
    run = run_agent(db, new_run(db, user, feedback))
    assert run.status == "awaiting_confirmation"
    assert run.token_used == 0
    assert [t["name"] for t in run.trace if t["kind"] == "tool"] == ["search_release_notes", "find_similar_feedback", "draft_feedback_ticket"]
    assert run.result["draft"]["evidence_ids"] == ["note-2.4-damage"]
    assert not db.scalar(select(AgentTicket))
    assert run.snapshot["input"]["text"] == feedback.text


def test_missing_version_abstains(store):
    db, _, user, feedback = store
    feedback.version = "9.9"; db.commit()
    run = run_agent(db, new_run(db, user, feedback))
    assert run.status == "needs_information"
    assert run.result["draft"] is None
    assert run.result["evidence_ids"] == []


def test_tool_arguments_sources_and_tenant_isolation(store):
    db, _, user, feedback = store
    other = Tenant(name="Other"); db.add(other); db.flush()
    db.add(AgentFeedback(tenant_id=other.id, text="火球技能伤害异常 secret", version="2.4"))
    db.add(AgentFeedback(tenant_id=user.tenant_id, text="火球技能伤害异常 same", version="2.4")); db.commit()
    evidence = {}
    result = invoke_tool("find_similar_feedback", {"query": "火球技能伤害异常"}, db, user.tenant_id, feedback.id, "2.4", evidence)
    assert len(result["results"]) == 1
    assert "secret" not in json.dumps(result)
    for name, args in [("execute_shell", {}), ("search_release_notes", {"query": "伤害", "version": "9.9"}), ("find_similar_feedback", {"query": "damage", "extra": "ignored?"})]:
        with pytest.raises(ValueError):
            invoke_tool(name, args, db, user.tenant_id, feedback.id, "2.4", evidence)
    with pytest.raises(ValueError, match="not retrieved"):
        invoke_tool("draft_feedback_ticket", {"title": "test title", "summary": "test summary", "category": "balance", "owner": "game_design", "evidence_ids": ["fake"]}, db, user.tenant_id, feedback.id, "2.4", evidence)


def test_failures_are_persisted_and_budgets_stop(store):
    db, _, user, feedback = store
    def crash(*_):
        raise RuntimeError("provider unavailable")
    run = run_agent(db, new_run(db, user, feedback), crash)
    assert run.status == "failed" and "provider unavailable" in run.error_message
    assert run.trace[0]["status"] == "failed"
    repeated = lambda *_: {"calls": [{"id": "repeat", "name": "search_release_notes", "arguments": {"query": "伤害", "version": "2.4"}}], "tokens": 0}
    run = run_agent(db, new_run(db, user, feedback), repeated)
    assert run.status == "failed" and "Maximum agent steps" in run.error_message
    run = run_agent(db, new_run(db, user, feedback), lambda *_: {"result": {}, "tokens": 12001})
    assert run.status == "failed" and "Token budget" in run.error_message


def test_bad_tool_is_observed_and_can_recover(store):
    db, _, user, feedback = store
    def adapter(messages, _):
        if not any(m["role"] == "tool" for m in messages):
            return {"calls": [{"id": "bad", "name": "find_similar_feedback", "arguments": "invalid json"}], "tokens": 0}
        return {"result": {"category": "unknown", "owner": "manual_review", "summary": "工具失败，需要人工补充资料。", "evidence_ids": [], "next_action": "needs_information"}, "tokens": 0}
    run = run_agent(db, new_run(db, user, feedback), adapter)
    assert run.status == "needs_information"
    assert any(t["kind"] == "tool" and t["status"] == "failed" for t in run.trace)


def test_unretrieved_evidence_and_missing_draft_fail(store):
    db, _, user, feedback = store
    result = {"category": "bug", "owner": "engineering", "summary": "请核实问题。", "evidence_ids": ["made-up"], "next_action": "confirm_ticket"}
    run = run_agent(db, new_run(db, user, feedback), lambda *_: {"result": result})
    assert run.status == "failed" and "not retrieved" in run.error_message


def test_real_function_call_request_and_observations(monkeypatch, store):
    db, _, user, feedback = store
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_retry_backoff", 0)
    responses = [
        {"tool_calls": [{"id": "n1", "type": "function", "function": {"name": "search_release_notes", "arguments": '{"query":"火球伤害","version":"2.4"}'}}]},
        {"tool_calls": [{"id": "d1", "type": "function", "function": {"name": "draft_feedback_ticket", "arguments": json.dumps({"title": "火球伤害异常", "summary": "需人工核实伤害报告。", "category": "balance", "owner": "game_design", "evidence_ids": ["note-2.4-damage"]})}}]},
        {"content": json.dumps({"category": "balance", "owner": "game_design", "summary": "请确认草稿并核实复现步骤。", "evidence_ids": ["note-2.4-damage"], "next_action": "confirm_ticket"})},
    ]
    captured = []
    def post(url, **kwargs):
        captured.append(copy.deepcopy(kwargs["json"]))
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": responses.pop(0)}], "usage": {"total_tokens": 12}})
    monkeypatch.setattr("app.llm.httpx.post", post)
    run = run_agent(db, new_run(db, user, feedback, "openai"))
    assert run.status == "awaiting_confirmation" and run.token_used == 36
    assert captured[0]["tool_choice"] == "auto"
    assert captured[1]["messages"][-1]["role"] == "tool"
    assert "note-2.4-damage" in captured[1]["messages"][-1]["content"]


@pytest.fixture
def client(store, monkeypatch):
    import app.main as main
    import app.agent_api as agent_api
    db, factory, user, feedback = store
    monkeypatch.setattr(main, "engine", db.bind)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(agent_api, "SessionLocal", factory)
    monkeypatch.setattr("app.worker.SessionLocal", factory)
    def database():
        with factory() as session:
            yield session
    main.app.dependency_overrides[get_db] = database
    with TestClient(main.app) as test_client:
        yield test_client, {"Authorization": f"Bearer {create_token(user)}"}
    main.app.dependency_overrides.clear()


def test_api_confirmation_idempotency_and_missing_key(client, store, monkeypatch):
    c, headers = client
    db, _, user, feedback = store
    response = c.post("/api/v1/agent/runs", headers=headers, json={"feedback_id": feedback.id})
    assert response.status_code == 202
    run_id = response.json()["id"]
    assert c.get(f"/api/v1/agent/runs/{run_id}", headers=headers).json()["status"] == "awaiting_confirmation"
    first = c.post(f"/api/v1/agent/runs/{run_id}/confirm", headers=headers)
    second = c.post(f"/api/v1/agent/runs/{run_id}/confirm", headers=headers)
    assert first.status_code == 200 and first.json()["id"] == second.json()["id"]
    assert len(c.get("/api/v1/agent/tickets", headers=headers).json()) == 1
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert c.post("/api/v1/agent/runs", headers=headers, json={"feedback_id": feedback.id, "mode": "openai"}).status_code == 422
    assert c.post("/api/v1/agent/feedbacks", headers=headers, json={"text": "   "}).status_code == 422


def test_api_cross_tenant_cannot_read_confirm_or_run(client, store):
    c, headers = client
    db, _, user, feedback = store
    run_id = c.post("/api/v1/agent/runs", headers=headers, json={"feedback_id": feedback.id}).json()["id"]
    other = Tenant(name="Other tenant"); db.add(other); db.flush()
    stranger = User(tenant_id=other.id, name="Other", email="other@test.dev", password_hash="unused")
    db.add(stranger); db.commit()
    h = {"Authorization": f"Bearer {create_token(stranger)}"}
    assert c.get(f"/api/v1/agent/runs/{run_id}", headers=h).status_code == 404
    assert c.post(f"/api/v1/agent/runs/{run_id}/confirm", headers=h).status_code == 404
    assert c.post("/api/v1/agent/runs", headers=h, json={"feedback_id": feedback.id}).status_code == 404
    assert c.get("/api/v1/agent/runs", headers=h).json() == []
    assert c.get("/api/v1/agent/runs").status_code == 401


def test_evaluation_is_offline_labelled_and_does_not_create_tickets():
    from app.agent_evaluation import evaluate
    report = evaluate("mock")
    assert report["synthetic"] and report["sample_count"] == 8
    assert all(r["total_tokens"] == 0 for r in report["reports"])
    agent = report["reports"][-1]
    assert agent["metrics"]["safe_completion"] == 100
    assert next(c for c in agent["cases"] if c["case_id"] == "duplicate")["duplicate_retrieved"]


def test_workflow_snapshot_survives_draft_edit(store):
    from app.worker import execute_workflow_task
    from unittest.mock import patch
    db, factory, user, _ = store
    graph = {"nodes": [{"id": "t", "type": "trigger"}, {"id": "o", "type": "output", "data": {"config": {"template": "frozen version"}}}], "edges": [{"source": "t", "target": "o"}]}
    workflow = Workflow(tenant_id=user.tenant_id, name="Snapshot test", graph={"nodes": []})
    db.add(workflow); db.flush()
    execution = Execution(tenant_id=user.tenant_id, workflow_id=workflow.id)
    db.add(execution); db.flush()
    db.add(WorkflowRunSnapshot(execution_id=execution.id, graph=graph, published_version=1)); db.commit()
    with patch("app.worker.SessionLocal", factory):
        execute_workflow_task(execution.id)
    db.refresh(execution)
    assert execution.status == "success" and execution.output_data == {"result": "frozen version"}


def test_workflow_api_runs_latest_published_snapshot(client, store):
    c, headers = client
    db, _, user, _ = store
    graph = {"nodes": [{"id": "t", "type": "trigger"}, {"id": "o", "type": "output", "data": {"config": {"template": "published"}}}], "edges": [{"source": "t", "target": "o"}]}
    workflow_id = c.post("/api/v1/workflows", headers=headers, json={"name": "Published test", "graph": graph}).json()["id"]
    assert c.post(f"/api/v1/workflows/{workflow_id}/publish", headers=headers).status_code == 200
    graph["nodes"][-1]["data"]["config"]["template"] = "unpublished edit"
    c.put(f"/api/v1/workflows/{workflow_id}", headers=headers, json={"graph": graph})
    response = c.post(f"/api/v1/workflows/{workflow_id}/execute", headers=headers, json={"input_data": {}})
    assert response.status_code == 200
    execution_id = response.json()["id"]
    result = c.get(f"/api/v1/executions/{execution_id}", headers=headers).json()
    assert result["output_data"] == {"result": "published"}
    snapshot = db.get(WorkflowRunSnapshot, execution_id)
    assert snapshot.published_version == 1


def test_bad_tools_exceed_call_budget_and_duration_stops(store, monkeypatch):
    db, _, user, feedback = store
    too_many = lambda *_: {"calls": [{"id": str(i), "name": "find_similar_feedback", "arguments": {"query": "伤害"}} for i in range(4)]}
    run = run_agent(db, new_run(db, user, feedback), too_many)
    assert run.status == "failed" and "Tool-call budget" in run.error_message
    run = new_run(db, user, feedback)
    run.snapshot = {**run.snapshot, "limits": {**run.snapshot["limits"], "max_duration_seconds": 0}}
    db.commit()
    run_agent(db, run)
    assert run.status == "failed" and "duration budget" in run.error_message


def test_release_note_search_ignores_generic_version_words(store):
    db, _, user, feedback = store
    result = invoke_tool("search_release_notes", {"query": "2.4 更新后火球技能伤害异常，请核实倍率。", "version": "2.4"}, db, user.tenant_id, feedback.id, "2.4", {})
    assert [n["id"] for n in result["results"]] == ["note-2.4-damage"]


def test_workflow_failure_logs_the_failing_node(store):
    from app.engine import execute_graph
    db, _, user, _ = store
    graph = {"nodes": [{"id": "t", "type": "trigger"}, {"id": "bad", "type": "unsupported"}], "edges": [{"source": "t", "target": "bad"}]}
    workflow = Workflow(tenant_id=user.tenant_id, name="Failure test", graph=graph)
    db.add(workflow); db.flush()
    execution = Execution(tenant_id=user.tenant_id, workflow_id=workflow.id)
    db.add(execution); db.commit()
    execute_graph(db, execution, graph)
    failure = db.scalar(select(ExecutionLog).where(ExecutionLog.execution_id == execution.id, ExecutionLog.status == "failed"))
    assert execution.status == "failed" and failure.node_id == "bad"
