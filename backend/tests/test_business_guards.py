import json
import httpx
import pytest
from test_agent import store
from test_business import task
from app.business_agent import snapshot, invoke, run_business
from app.agent_runtime import real_turn
from app.config import settings


@pytest.mark.parametrize("text,status", [
    ("A102 退款需要审核吗？不要生成工单。", "completed"),
    ("A103 配送情况怎样，无需创建工单。", "completed"),
    ("A101 和 A102 退款请给其中一个写申诉。", "needs_information"),
    ("A103 正在运输，能使用退款规则吗？", "needs_information"),
    ("A101 的配送逾期规则？", "needs_information"),
    ("A102 退款申请，请创建工单。", "awaiting_confirmation"),
    ("订单 a101 退款，A101 是我的订单。", "completed"),
])
def test_business_intent_and_applicability(store, text, status):
    run = run_business(store[0], task(store, text))
    assert run.status == status
    if status != "awaiting_confirmation":
        assert not run.result.get("draft")
        assert not any(t.get("name") == "draft_ticket" for t in run.trace)


@pytest.mark.parametrize("text,order,policy", [
    ("A102 退款不要工单", "A102", "refund-v1"),
    ("A102 和 A101 退款生成工单", "A102", "refund-v1"),
    ("A103 退款生成工单", "A103", "refund-v1"),
    ("A101 退款生成工单", "A102", "refund-v1"),
])
def test_real_tool_requests_cannot_bypass_guards(text, order, policy):
    snap = snapshot(text, "openai")
    evidence = {}
    invoke("get_order", {"order_id": order}, snap, evidence)
    invoke("search_policy", {"query": "退款"}, snap, evidence)
    with pytest.raises(ValueError):
        invoke("draft_ticket", {"order_id": order, "title": "服务工单", "summary": "模型声称可以提交", "evidence_ids": ["order-" + order, policy]}, snap, evidence)


def test_model_cannot_answer_with_inapplicable_retrieved_policy(store):
    count = 0
    def bad_model(*_):
        nonlocal count
        count += 1
        if count == 1:
            return {"calls": [{"id": "order", "name": "get_order", "arguments": {"order_id": "A103"}}, {"id": "policy", "name": "search_policy", "arguments": {"query": "退款"}}]}
        return {"result": {"summary": "运输中的订单可以套用签收退款规则", "next_action": "answer", "evidence_ids": ["order-A103", "refund-v1"]}}
    run = run_business(store[0], task(store, "A103 退款政策"), bad_model)
    assert run.status == "failed" and "applicable" in run.error_message


@pytest.mark.parametrize("endpoint,deepseek", [("https://api.deepseek.com", True), ("https://api.deepseek.com/v1", True), ("https://example.test/v1", False)])
def test_deepseek_request_contract(monkeypatch, endpoint, deepseek):
    monkeypatch.setattr(settings, "openai_base_url", endpoint)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    def post(url, json, **kwargs):
        assert (json.get("thinking") == {"type": "disabled"}) == deepseek
        assert url == endpoint + "/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": {"content": '```json\n{"summary":"请补充订单号","next_action":"needs_information"}\n```'}}], "usage": {"total_tokens": 30, "prompt_tokens": 20, "completion_tokens": 10}})
    monkeypatch.setattr("app.llm.httpx.post", post)
    response = real_turn([], snapshot("我想退款", "openai"))
    assert response["result"]["next_action"] == "needs_information"
    assert response["usage"]["completion_tokens"] == 10


def test_configuration_check_never_echoes_key(monkeypatch):
    from app.check_model import configuration_errors
    monkeypatch.setattr(settings, "openai_api_key", "do-not-echo-this")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.deepseek.com")
    assert configuration_errors() == []
    monkeypatch.setattr(settings, "openai_base_url", "https://api.deepseek.com/incorrect")
    assert "do-not-echo-this" not in json.dumps(configuration_errors())
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert any("Missing" in e for e in configuration_errors())
