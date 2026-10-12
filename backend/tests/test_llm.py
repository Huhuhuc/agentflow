"""LLM 网关测试：验证 Mock 双模式与真实 OpenAI-compatible 调用路径。

真实模式用拦截器替换 httpx.post，无需真实 API Key，即可证明：
- 请求构造正确（endpoint / 鉴权头 / model / temperature / 结构化输出）
- 提示词模板 {{trigger.message}} 被正确解析
- 响应解析正确（token 统计 + JSON schema 结构化结果）
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test-llm.db"

import httpx
import pytest

import app.llm as llm_module
from app.config import settings
from app.llm import LLMError, call_llm

SUCCESS_PAYLOAD = {
    "choices": [{"message": {"content": '{"category":"complaint"}'}}],
    "usage": {"total_tokens": 42},
}


def _response(status: int, payload: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """构造真实 httpx.Response，使 raise_for_status() 走真实的错误分支。"""
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    return httpx.Response(status, json=payload or {}, headers=headers or {}, request=request)


@pytest.fixture
def real_mode(monkeypatch):
    """切到真实模式并固定重试参数，避免受本地 .env 影响。"""
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-123")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.example.com/v1")
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_retry_backoff", 0.5)
    sleeps: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def test_mock_classify_without_prompt():
    """未配置提示词 → 走确定性意图分类（零 Key 演示）。"""
    output, tokens = call_llm({}, {"trigger": {"message": "我要投诉并退款"}})
    assert output["category"] == "complaint"
    assert 0 < output["confidence"] <= 1
    assert tokens > 0

    output2, _ = call_llm({}, {"trigger": {"message": "企业版怎么配置知识库？"}})
    assert output2["category"] == "inquiry"


def test_mock_prompt_with_schema_is_deterministic():
    """配置提示词但仍是 mock 模式 → 返回可复现的结构化占位。"""
    config = {
        "user_prompt": "对工单分类：{{trigger.message}}",
        "json_schema": {"type": "object", "properties": {"category": {"type": "string"}}},
    }
    output, tokens = call_llm(config, {"trigger": {"message": "你好"}})
    assert "structured" in output
    assert "category" in output["structured"]
    assert tokens > 0


def test_real_call_builds_standard_openai_request(monkeypatch):
    """真实模式：验证真正发出标准 OpenAI-compatible 请求并解析响应。"""
    captured: dict = {}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": '{"category":"complaint","confidence":0.91}'}}],
                "usage": {"total_tokens": 123},
            }

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-123")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.example.com/v1")

    config = {
        "model": "gpt-4o-mini",
        "system_prompt": "你是客服助手。",
        "user_prompt": "请对以下工单分类：{{trigger.message}}",
        "temperature": 0.3,
        "json_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}, "confidence": {"type": "number"}},
            "required": ["category", "confidence"],
            "additionalProperties": False,
        },
    }
    context = {"trigger": {"message": "我要投诉退款"}}
    output, tokens = call_llm(config, context)

    # 1) endpoint 与鉴权
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test-123"
    # 2) 请求体
    body = captured["json"]
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.3
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    # 3) 提示词模板被解析
    assert "我要投诉退款" in body["messages"][1]["content"]
    # 4) 结构化输出声明
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    # 5) 响应解析
    assert tokens == 123
    assert output["model"] == "gpt-4o-mini"
    assert output["structured"]["category"] == "complaint"
    assert output["structured"]["confidence"] == 0.91


def test_real_call_falls_back_to_mock_without_key(monkeypatch):
    """llm_mode=openai 但缺少 Key → 安全回退到 Mock，不会崩溃。"""
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    output, tokens = call_llm({}, {"trigger": {"message": "退款投诉"}})
    assert output["category"] == "complaint"
    assert tokens > 0


def test_retries_transient_5xx_then_succeeds(monkeypatch, real_mode):
    """503 属于瞬时故障 → 指数退避重试，最终成功。"""
    calls: list[int] = []

    def fake_post(url, json, headers, timeout):
        calls.append(1)
        return _response(503) if len(calls) < 3 else _response(200, SUCCESS_PAYLOAD)

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    output, tokens = call_llm({"user_prompt": "分类：{{trigger.message}}"}, {"trigger": {"message": "退款"}})

    assert len(calls) == 3
    assert output["attempts"] == 3
    assert tokens == 42
    assert real_mode == [0.5, 1.0]  # 指数退避：0.5 → 1.0


def test_retries_on_network_error_then_gives_up(monkeypatch, real_mode):
    """连接超时属于可重试故障；超过上限后抛 LLMError 而非静默失败。"""
    calls: list[int] = []

    def fake_post(url, json, headers, timeout):
        calls.append(1)
        raise httpx.ConnectTimeout("connection timed out")

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    with pytest.raises(LLMError) as err:
        call_llm({"user_prompt": "hi"}, {})

    assert len(calls) == 3  # 1 次首发 + 2 次重试
    assert "3 attempt(s)" in str(err.value)


def test_does_not_retry_on_auth_error(monkeypatch, real_mode):
    """401 是确定性失败 → 立即失败，不浪费重试与等待。"""
    calls: list[int] = []

    def fake_post(url, json, headers, timeout):
        calls.append(1)
        return _response(401)

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    with pytest.raises(LLMError) as err:
        call_llm({"user_prompt": "hi"}, {})

    assert len(calls) == 1
    assert "401" in str(err.value)
    assert real_mode == []  # 未发生任何等待


def test_respects_retry_after_header(monkeypatch, real_mode):
    """429 限流时优先遵守服务端 Retry-After，而不是本地退避。"""
    calls: list[int] = []

    def fake_post(url, json, headers, timeout):
        calls.append(1)
        if len(calls) == 1:
            return _response(429, headers={"Retry-After": "2"})
        return _response(200, SUCCESS_PAYLOAD)

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    output, _ = call_llm({"user_prompt": "hi"}, {})

    assert real_mode == [2.0]  # 用了服务端指定的 2s，而非本地 0.5s
    assert output["attempts"] == 2


def test_node_level_max_retries_override(monkeypatch, real_mode):
    """节点可通过 config.max_retries 关闭重试（如对时延敏感的节点）。"""
    calls: list[int] = []

    def fake_post(url, json, headers, timeout):
        calls.append(1)
        return _response(503)

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    with pytest.raises(LLMError):
        call_llm({"user_prompt": "hi", "max_retries": 0}, {})

    assert len(calls) == 1
