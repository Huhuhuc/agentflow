import pytest
from sqlalchemy import select

from app.business_agent import invoke
from app.business_agent import run_business
from app.config import settings
from app.models import AgentFeedback, AgentRun, PolicyIndex, ServicePolicy
from app.policy_index import claim, enqueue, finish
from app.service_catalogue import database_snapshot, seed_catalogue
from test_agent import store


class FakeEmbedder:
    def queries(self, texts):
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def tenant_snapshot(store, monkeypatch):
    db, factory, user, _ = store
    seed_catalogue(db, user.tenant_id)
    policy = db.scalar(select(ServicePolicy).where(
        ServicePolicy.tenant_id == user.tenant_id, ServicePolicy.slug == "refund"))
    index = enqueue(db, user.tenant_id, policy.id, "fixture-retrieval-v1")
    db.commit()
    token = claim(db, user.tenant_id, index.id)
    assert token
    assert finish(db, user.tenant_id, index.id, token, vectors=[[1.0, 0.0] for _ in index.chunks])
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "embedding_revision", "fixture-retrieval-v1")
    monkeypatch.setattr(settings, "retrieval_abstention_threshold", None)
    monkeypatch.setattr("app.business_retrieval._embedder", lambda *_: FakeEmbedder())
    db.expire_all()
    check = db.get(PolicyIndex, index.id)
    assert check.status == "ready" and check.model_revision == "fixture-retrieval-v1", (check.status, check.model_revision)
    snapshot = database_snapshot(db, user.tenant_id, "A101 退款", "mock")
    assert snapshot["retrieval_indexes"], snapshot["retrieval"]
    assert all("vector" not in mapping for index in snapshot["retrieval_indexes"] for mapping in index["mapped_chunks"])
    return db, user, snapshot


def policy_items(snapshot):
    return [item for item in snapshot["knowledge"] if item["topic"] == "refund"]


def test_hybrid_uses_ready_same_revision_index(tenant_snapshot):
    db, user, snapshot = tenant_snapshot
    evidence = {}
    result = invoke("search_policy", {"query": "退款"}, snapshot, evidence, db, user.tenant_id)
    assert result["retrieval"] == "hybrid", result
    assert result["fallback_reason"] is None
    assert result["results"]
    assert all(item["id"] in {e["id"] for e in policy_items(snapshot)} for item in result["results"])


def test_missing_index_is_explicit_lexical_fallback(store, monkeypatch):
    db, _, user, _ = store
    seed_catalogue(db, user.tenant_id)
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "embedding_revision", "fixture-retrieval-v1")
    snapshot = database_snapshot(db, user.tenant_id, "A101 退款", "mock")
    result = invoke("search_policy", {"query": "退款"}, snapshot, {}, db, user.tenant_id)
    assert result["retrieval"] == "lexical_fallback"
    assert result["fallback_reason"] == "index_missing"
    assert result["results"]


def test_threshold_abstains_without_returning_evidence(tenant_snapshot, monkeypatch):
    db, user, snapshot = tenant_snapshot
    snapshot["retrieval"]["threshold"] = 2.0
    result = invoke("search_policy", {"query": "退款"}, snapshot, {}, db, user.tenant_id)
    assert result["retrieval"] == "hybrid", result
    assert result["abstained"] is True
    assert result["results"] == []


def test_new_policy_without_ready_index_does_not_use_old_index(tenant_snapshot, monkeypatch):
    db, user, _ = tenant_snapshot
    old = db.scalar(select(ServicePolicy).where(
        ServicePolicy.tenant_id == user.tenant_id, ServicePolicy.slug == "refund", ServicePolicy.version == 1))
    db.add(ServicePolicy(tenant_id=user.tenant_id, slug="refund", version=2, title="Refund v2",
                         text="新版退款规则要求人工核验订单状态。", topic="refund", order_status="delivered", active=True))
    db.commit()
    snapshot = database_snapshot(db, user.tenant_id, "A101 退款", "mock")
    assert all(item["version"] == 2 for item in snapshot["knowledge"] if item["topic"] == "refund")
    result = invoke("search_policy", {"query": "退款"}, snapshot, {}, db, user.tenant_id)
    assert result["retrieval"] == "lexical_fallback"
    assert result["fallback_reason"] == "index_missing"
    assert all(item["version"] == 2 for item in result["results"])
    assert old.version == 1


def test_model_cannot_answer_after_abstention(tenant_snapshot):
    db, user, snapshot = tenant_snapshot
    snapshot["retrieval"]["threshold"] = 2.0
    feedback = AgentFeedback(tenant_id=user.tenant_id, text="A101 退款", version="service-v2")
    db.add(feedback); db.flush()
    run = AgentRun(tenant_id=user.tenant_id, feedback_id=feedback.id, snapshot=snapshot)
    db.add(run); db.commit()
    count = 0

    def ignores_abstention(messages, _):
        nonlocal count
        count += 1
        if count == 1:
            return {"calls": [
                {"id": "order", "name": "get_order", "arguments": {"order_id": "A101"}},
                {"id": "policy", "name": "search_policy", "arguments": {"query": "退款"}},
            ]}
        return {"result": {"summary": "根据政策可以退款。", "evidence_ids": ["order-A101", "refund@1#p1-c1"], "next_action": "answer"}}

    run_business(db, run, ignores_abstention)
    assert run.status == "needs_information"
    assert run.result["evidence_ids"] == []
    assert "未达到配置的证据阈值" in run.result["summary"]


def test_foreign_index_reference_falls_back_under_tenant_filter(tenant_snapshot):
    db, user, snapshot = tenant_snapshot
    snapshot["retrieval_indexes"][0]["index_id"] = "foreign-index-id"
    result = invoke("search_policy", {"query": "退款"}, snapshot, {}, db, user.tenant_id)
    assert result["retrieval"] == "lexical_fallback"
    assert result["fallback_reason"] == "ValueError"


def test_embedding_timeout_falls_back_to_lexical(tenant_snapshot, monkeypatch):
    db, user, snapshot = tenant_snapshot
    class SlowEmbedder:
        def queries(self, _):
            import time
            time.sleep(0.05)
            return [[1.0, 0.0]]
    monkeypatch.setattr("app.business_retrieval._embedder", lambda *_: SlowEmbedder())
    monkeypatch.setattr(settings, "retrieval_embedding_timeout_seconds", 0.001)
    result = invoke("search_policy", {"query": "退款"}, snapshot, {}, db, user.tenant_id)
    assert result["retrieval"] == "lexical_fallback"
    assert result["fallback_reason"] == "TimeoutError"
    import time
    time.sleep(0.06)
