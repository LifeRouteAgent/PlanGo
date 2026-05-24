from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.services.trace_recorder import record_trace_event
from app.services.tool_harness import ToolHarness


def is_llm_enabled() -> bool:
    """判断当前环境是否具备调用大模型的条件。

    项目默认使用 MiMo 的 OpenAI-compatible 接口。测试环境或本地未配置 key 时，
    上层 Agent 会自动走规则兜底，不影响 DAG 的可执行性。
    """

    return bool(settings.mimo_api_key)


def call_chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    timeout_seconds: int = 20,
    max_completion_tokens: int = 1024,
) -> str | None:
    """调用 OpenAI-compatible chat completions 接口并返回文本内容。

    这里刻意只封装项目需要的最小能力，避免引入额外 SDK。任何网络错误、
    服务端错误或响应格式异常都会返回 None，由上层使用确定性规则兜底。
    """

    if not is_llm_enabled():
        record_trace_event(
            "llm_result",
            {
                "provider": "mimo",
                "model": settings.mimo_model,
                "success": False,
                "source": "disabled",
                "latency_ms": 0,
                "attempts": 0,
                "error": "MIMO_API_KEY is empty",
                "content_preview": "",
            },
        )
        return None

    url = settings.mimo_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.mimo_model,
        "messages": messages,
        # 按 MiMo 官方 OpenAI-compatible 示例传参，避免兼容层因为缺少生成参数而拒绝请求。
        "max_completion_tokens": max_completion_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        "stream": False,
        "stop": None,
        "frequency_penalty": 0,
        "presence_penalty": 0,
    }
    headers = {
        "Authorization": f"Bearer {settings.mimo_api_key}",
        "Content-Type": "application/json",
    }

    def _request() -> str | None:
        """实际 HTTP 调用放进闭包，交给 ToolHarness 做 timeout/retry/fallback。"""

        response = httpx.post(url, json=payload, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

    harness = ToolHarness(
        name="llm.mimo.chat_completion",
        timeout_seconds=timeout_seconds + 2,
        max_retries=1,
        fallback=lambda: None,
    )
    result = harness.run(_request)
    record_trace_event(
        "llm_result",
        {
            "provider": "mimo",
            "model": settings.mimo_model,
            "success": bool(result.success and result.data),
            "source": result.source,
            "latency_ms": result.latency_ms,
            "attempts": result.attempts,
            "error": result.error,
            "content_preview": str(result.data)[:600] if result.data else "",
        },
    )
    return str(result.data) if result.success and result.data else None


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """从模型输出中提取 JSON 对象。

    即使 prompt 要求只输出 JSON，模型仍可能包一层 Markdown 代码块。
    因此这里做一次宽松解析：先直接解析，失败后再截取第一个 `{...}`。
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

    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
