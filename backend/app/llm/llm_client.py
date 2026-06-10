from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from app.config import settings
from app.llm.prompt_registry import get_prompt_spec
from app.observability.trace_recorder import TraceRecorder
from app.tools.tool_harness import ToolHarness
from app.tools.tool_policy import ToolCallRequest

# 模块级复用连接池，避免每次 LLM 调用都新建 TCP+TLS 连接
_llm_http_client: httpx.Client | None = None


def _get_llm_client(timeout_seconds: int) -> httpx.Client:
    """延迟初始化并返回带连接池的 httpx.Client。

    超时拆分为 connect/read/write：
    - connect 固定 5s，避免 DNS/TLS 无限等待
    - read 使用调用方传入的 timeout_seconds
    - ToolHarness._run_with_timeout 作为硬安全网（timeout_seconds+2）
    """
    global _llm_http_client
    if _llm_http_client is None or _llm_http_client.timeout.read != timeout_seconds:
        _llm_http_client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=float(timeout_seconds), write=10.0, pool=5.0),
            # 设置: 活跃的最大空闲连接数, 最大并发连接数
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            http2=True,
        )
    return _llm_http_client


def call_chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    timeout_seconds: int = 20,
    max_completion_tokens: int = 1024,
    prompt_name: str | None = None,
    schema_name: str | None = None,
) -> str | None:
    """调用 OpenAI-compatible chat completions 接口并返回文本内容。

    DeepSeek 官方 OpenAI 示例使用 base_url=https://api.deepseek.com；对应 HTTP
    地址就是 https://api.deepseek.com/chat/completions，不需要额外拼 /v1。
    这里继续用轻量 httpx 封装，便于 ToolHarness 统一记录 timeout、retry、fallback。
    """

    # 这里直接改成硬编码 (即不再区分 MiMo 还是 DeepSeek, 统一使用 DeepSeek). 以后再考虑兼容性
    provider = settings.llm_provider
    model = settings.deepseek_model
    api_key = settings.deepseek_api_key
    base_url = settings.deepseek_base_url

    prompt_spec = get_prompt_spec(prompt_name)
    trace_base = {
        "provider": provider,
        "model": model,
        "prompt_name": prompt_spec.prompt_name,
        "prompt_version": prompt_spec.prompt_version,
        "schema_name": schema_name or prompt_spec.schema_name,
        "schema_version": prompt_spec.schema_version,
    }

    if os.environ.get("PYTEST_CURRENT_TEST"):
        TraceRecorder.record(
            "llm_result",
            {
                **trace_base,
                "success": False,
                "source": "pytest_disabled",
                "latency_ms": 0,
                "attempts": 0,
                "error": "LLM calls are disabled during pytest; using deterministic fallback.",
                "content_preview": "",
            },
        )
        return None

    if not api_key:
        TraceRecorder.record(
            "llm_result",
            {
                **trace_base,
                "success": False,
                "source": "disabled",
                "latency_ms": 0,
                "attempts": 0,
                "error": f"{provider.upper()} API key is empty",
                "content_preview": "",
            },
        )
        return None

    url = _chat_completions_url(base_url)
    # 以后默认就是 DeepSeek 直接硬编码了. 后续再考虑兼容性的问题
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.95,
        "stream": False,
        "max_tokens": max_completion_tokens,
        "reasoning_effort": settings.deepseek_reasoning_effort,
    }

    if settings.deepseek_thinking_enabled:
        payload["thinking"] = {"type": "enabled"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _request() -> str | None:
        """实际 HTTP 调用交给 ToolHarness 处理 retry/fallback。

        timeout 由 httpx.Client 在连接层控制（connect/read/write 分离），
        ToolHarness._run_with_timeout 作为硬安全网兜底。
        """
        client = _get_llm_client(timeout_seconds)
        try:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            content_type = response.headers.get("content-type", "")
            body_preview = response.text[:800].replace("\n", " ")
            error_log = (
                "{} "
                f"status={response.status_code} content_type={content_type} url={url} "
                f"body_preview={body_preview!r}"
            )
            if isinstance(exc, httpx.HTTPStatusError):
                raise ValueError(error_log.format("LLM HTTP error"))
            else:
                raise ValueError(error_log.format("LLM response is not JSON"))

    harness = ToolHarness(
        name=f"llm.{provider}.chat_completion",
        timeout_seconds=timeout_seconds + 2,
        max_retries=1,
        fallback=lambda: None,
    )
    result = harness.run_request(
        ToolCallRequest(
            tool_name=f"llm.{provider}.chat_completion",
            risk_level=1,
            user_id="system",
            params={**trace_base},
        ),
        _request,
    )
    data = result.data if isinstance(result.data, dict) else {}
    content = data.get("value") if isinstance(data, dict) else None
    TraceRecorder.record(
        "llm_result",
        {
            **trace_base,
            "success": bool(result.success and content),
            "source": result.source,
            "latency_ms": result.latency_ms,
            "attempts": result.attempts,
            "error": result.error_code,
            "content_preview": str(content)[:600] if content else "",
        },
    )
    return str(content) if result.success and content else None


def _chat_completions_url(base_url: str) -> str:
    """把 OpenAI-compatible base_url 转为 chat completions URL。

    如果用户已经把完整 /chat/completions 写进配置，就直接使用；否则只拼接一次。
    DeepSeek 官方 base_url 不带 /v1，因此这里不会强行补 /v1。
    """

    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """从模型输出中提取 JSON 对象。

    即使 prompt 要求只输出 JSON，模型仍可能包一层 Markdown 代码块。
    因此这里先直接解析，失败后再截取第一个 `{...}` 做宽松解析。
    """

    if not text:
        return None

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*}", cleaned, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
