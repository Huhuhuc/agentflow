"""LLM 网关：在确定性 Mock 模式与真实 OpenAI-compatible 模式之间切换。

- `llm_mode == "openai"` 且配置了 `openai_api_key` 时，调用真实模型端点，
  支持 system/user prompt 模板、temperature 与 JSON schema 结构化输出。
- 否则进入 Mock 模式：节点未配置提示词时复用原有的确定性意图分类，
  配置提示词时返回可复现的结构化占位结果，保证零 API Key 也能完整演示。
"""

import json
import re
import time
from typing import Any

import httpx

from .config import settings


TOKEN_PATTERN = re.compile(r"\{\{\s*([^}]+)\s*\}\}")

# 可重试的 HTTP 状态：限流、请求超时、锁冲突与网关类 5xx。
# 其余 4xx（如 401 鉴权失败、400 参数错误）属于确定性失败，重试无意义。
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


def _resolve(template: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match) -> str:
        current: Any = context
        for part in match.group(1).strip().split("."):
            current = current.get(part, "") if isinstance(current, dict) else ""
        return json.dumps(current, ensure_ascii=False) if isinstance(current, (dict, list)) else str(current)

    return TOKEN_PATTERN.sub(replace, template or "")


def _mock_classify(context: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    source = json.dumps(context, ensure_ascii=False).lower()
    complaint_words = ["投诉", "退款", "complaint", "angry", "差评", "维权", "赔偿"]
    category = "complaint" if any(word in source for word in complaint_words) else "inquiry"
    confidence = 0.72 if category == "complaint" else 0.94
    text = "已根据知识库生成处理建议。" if category == "inquiry" else "已识别为投诉类工单，建议转人工跟进。"
    return {"category": category, "confidence": confidence, "text": text, "model": config.get("model", "mock-agent")}, 168


def _sample_value(spec: dict[str, Any]) -> Any:
    kind = spec.get("type")
    if kind == "integer":
        return 1
    if kind == "number":
        return 0.9
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    return "mock"


def _mock_prompt(config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    schema = config.get("json_schema")
    result: dict[str, Any] = {
        "model": config.get("model", "mock-agent"),
        "text": "（Mock 模式）已根据提示词生成确定性回复，配置真实 LLM 后此处返回模型输出。",
    }
    if schema:
        props = schema.get("properties", {})
        result["structured"] = {key: _sample_value(value) for key, value in props.items()}
    return result, 96


def call_llm(config: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """返回 (节点输出, token 消耗)。"""
    has_prompt = bool(config.get("system_prompt") or config.get("user_prompt"))
    if settings.llm_mode != "openai" or not settings.openai_api_key:
        if not has_prompt:
            return _mock_classify(context, config)
        return _mock_prompt(config)
    return _real_call(config, context)


def _retry_after_seconds(response: Any) -> float | None:
    """解析服务端的 Retry-After 头（秒数形式），优先于本地退避。"""
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _post_with_retry(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    max_retries: int,
    backoff: float,
    max_retry_delay: float | None = None,
) -> tuple[Any, int]:
    """带指数退避的 POST。返回 (响应, 实际尝试次数)。

    仅对网络故障与 RETRYABLE_STATUS 重试；确定性失败立即抛出，避免无谓等待。
    """
    for attempt in range(max_retries + 1):
        delay: float
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response, attempt + 1
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in RETRYABLE_STATUS or attempt == max_retries:
                raise LLMError(f"LLM request failed with HTTP {status} after {attempt + 1} attempt(s): {exc}") from exc
            delay = _retry_after_seconds(exc.response) or backoff * (2 ** attempt)
        except httpx.HTTPError as exc:
            if attempt == max_retries:
                raise LLMError(f"LLM request failed after {attempt + 1} attempt(s): {exc}") from exc
            delay = backoff * (2 ** attempt)
        if max_retry_delay is not None:
            delay = min(delay, max_retry_delay)
        if delay > 0:
            time.sleep(delay)
    raise LLMError("LLM request failed: retry loop exhausted")


def _real_call(config: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], int]:
    system = _resolve(config.get("system_prompt", ""), context)
    user = _resolve(config.get("user_prompt", ""), context)
    model = config.get("model") or settings.openai_model
    temperature = float(config.get("temperature", 0.2))
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    schema = config.get("json_schema")
    if schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "agent_output", "schema": schema, "strict": True},
        }
    max_retries = int(config.get("max_retries", settings.llm_max_retries))
    resp, attempts = _post_with_retry(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        payload,
        {"Authorization": f"Bearer {settings.openai_api_key}"},
        float(config.get("timeout", settings.llm_timeout)),
        max(max_retries, 0),
        max(float(settings.llm_retry_backoff), 0.0),
    )
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    tokens = int(usage.get("total_tokens", 0))
    output: dict[str, Any] = {"model": model, "text": content, "attempts": attempts}
    if schema:
        try:
            output["structured"] = json.loads(content)
        except json.JSONDecodeError:
            output["structured"] = {"raw": content}
    return output, tokens
