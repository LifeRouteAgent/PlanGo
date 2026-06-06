from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, TypeVar

from tenacity import RetryCallState, retry, stop_after_attempt, wait_exponential

from app.memory.memory_store import (
    FileMemoryStore,
    expires_at_from_ttl,
    make_cache_key,
    make_request_hash,
    ttl_seconds_for_tool,
)
from app.observability.trace_recorder import record_trace_event
from app.tools.tool_policy import ToolCallRequest, ToolCallResult, ToolPolicy

# todo: 这个类放在 services 文件夹下面是否合适呢?
logger = logging.getLogger("liferoute.tool_harness")

T = TypeVar("T")

_TOOL_EXECUTOR_MAX_WORKERS = 8
_TOOL_EXECUTOR = ThreadPoolExecutor(
    max_workers=_TOOL_EXECUTOR_MAX_WORKERS, thread_name_prefix="tool-harness"
)


@dataclass
class HarnessResult:
    """统一工具调用结果。

    这层不替代业务返回结构，只负责记录工具调用是否成功、耗时、来源和错误。
    调用方仍然可以决定失败后是抛错、走 fallback，还是继续返回降级结果。
    """

    success: bool
    data: Any = None
    error: str | None = None
    source: str = "live"
    latency_ms: int = 0
    attempts: int = 0


@dataclass
class ToolHarness:
    """本项目统一的工具可靠性封装。

    适用对象：
    - LLM：MiMo/OpenAI-compatible HTTP 调用
    - 数据库：MySQL 查询
    - PDF：导出渲染
    - 执行 mock：订座、购票、打车模拟
    - 后续高德：路线/POI/地理编码 API

    设计目标是 Demo 稳定：每个外部或慢调用都有 timeout、retry、fallback 和日志。
    # todo: 感觉这个类的名字不是很好, 和 harness 有啥关系呢? 让 gpt 重新取一个?
        能否通过 python 的注解或者叫函数装饰器实现这一点呢? 这样就不用每次新建一个对象
    """

    name: str
    timeout_seconds: float = 10
    max_retries: int = 1
    retry_backoff_seconds: float = 0.2
    fallback: Callable[..., T] | None = None
    # todo: 问一下 gpt 这个的含义
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> HarnessResult:
        """执行同步工具函数，并返回标准化结果。

        重试/退避由 tenacity 驱动；所有重试耗尽后走 fallback（如有）。
        工具函数本身通过模块级共享线程池执行，避免每次调用创建线程池。
        """

        _retry_state_ref: list[RetryCallState | None] = [None]

        def _capture_state(retry_state: RetryCallState) -> None:
            """tenacity before_sleep 回调：在下次重试前捕获 retry_state 用于计数。"""
            _retry_state_ref[0] = retry_state

        def _fallback(retry_state: RetryCallState) -> HarnessResult:
            """tenacity retry_error_callback：所有重试都失败后调用。"""
            if not self.fallback:
                return HarnessResult(
                    success=False,
                    error=str(retry_state.outcome.exception()) if retry_state.outcome else "",
                    source="failed",
                    attempts=retry_state.attempt_number,
                )

            fallback_started = time.perf_counter()
            try:
                data = self.fallback(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                self._record(False, 0, -1, "fallback", error)
                orig_error = str(retry_state.outcome.exception()) if retry_state.outcome else ""
                return HarnessResult(
                    success=False,
                    error=f"{orig_error}; fallback failed: {error}" if orig_error else error,
                    source="failed",
                    attempts=retry_state.attempt_number,
                )

            latency = int((time.perf_counter() - fallback_started) * 1000)
            self._record(True, latency, -1, "fallback", None)
            self._cache_result(args=args, kwargs=kwargs, data=data, source="fallback")
            return HarnessResult(
                success=True,
                data=data,
                source="fallback",
                latency_ms=latency,
                attempts=retry_state.attempt_number,
            )

        @retry(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(
                multiplier=self.retry_backoff_seconds, min=self.retry_backoff_seconds
            ),
            before_sleep=_capture_state,
            retry_error_callback=_fallback,
        )
        def _attempt() -> HarnessResult:
            """单次工具调用（含超时）；失败时抛异常让 tenacity 重试."""
            rs = _retry_state_ref[0]
            attempt = (rs.attempt_number + 1) if rs else 1
            started = time.perf_counter()
            try:
                data = self._run_with_timeout(fn, *args, **kwargs)
            except Exception as exc:
                latency = int((time.perf_counter() - started) * 1000)
                self._record(False, latency, attempt, "live", str(exc))
                raise
            latency = int((time.perf_counter() - started) * 1000)
            self._record(True, latency, attempt, "live", None)
            self._cache_result(args=args, kwargs=kwargs, data=data, source="live")
            return HarnessResult(
                success=True, data=data, source="live", latency_ms=latency, attempts=attempt
            )

        result = _attempt()

        return result

    def run_request(
        self,
        request: ToolCallRequest,
        fn: Callable[..., T],
        *args: Any,
        policy: ToolPolicy | None = None,
        **kwargs: Any,
    ) -> ToolCallResult:
        """按 ToolPolicy 执行治理后的工具调用。

        该方法用于新工具；旧调用仍可继续用 `run()`。它会记录请求、校验、确认、
        成功/失败/fallback 等更细 trace 事件，并输出统一 ToolCallResult。
        """

        policy = policy or ToolPolicy()
        request.requires_confirmation = policy.requires_confirmation(request.risk_level)
        if request.risk_level >= 3:
            request.idempotency_key = policy.ensure_idempotency_key(request)
        record_trace_event("tool_requested", _redact_request(request))
        issues = policy.validate(request)
        if issues:
            record_trace_event("tool_failed", {**_redact_request(request), "issues": issues})
            return {
                "success": False,
                "data": None,
                "error_code": issues[0]["code"],
                "source": "policy",
                "fetched_at": _now_iso(),
                "expires_at": None,
                "confidence": 0.0,
                "fallback_used": False,
                "attempts": 0,
                "latency_ms": 0,
            }
        if request.requires_confirmation:
            record_trace_event("tool_confirm_required", _redact_request(request))
        record_trace_event("tool_started", _redact_request(request))
        result = self.run(fn, *args, **kwargs)
        error_code = None if result.success else policy.classify_error(result.error)
        event_type = "tool_succeeded" if result.success else "tool_failed"
        record_trace_event(
            event_type,
            {
                **_redact_request(request),
                "error_code": error_code,
                "source": result.source,
                "attempts": result.attempts,
                "latency_ms": result.latency_ms,
            },
        )
        if result.source == "fallback":
            record_trace_event("tool_fallback_used", _redact_request(request))
        return {
            "success": bool(result.success),
            "data": result.data if isinstance(result.data, dict) else {"value": result.data},
            "error_code": error_code,
            "source": result.source,
            "fetched_at": _now_iso(),
            "expires_at": expires_at_from_ttl(ttl_seconds_for_tool(self.name)),
            "confidence": 1.0 if result.success else 0.0,
            "fallback_used": result.source == "fallback",
            "attempts": result.attempts,
            "latency_ms": result.latency_ms,
        }

    def _run_with_timeout(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """用共享线程池为同步函数加超时控制。"""
        future = _TOOL_EXECUTOR.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"{self.name} timeout after {self.timeout_seconds}s") from exc

    def _record(
        self,
        success: bool,
        latency_ms: int,
        attempt: int,
        source: str,
        error: str | None,
    ) -> None:
        """记录工具调用日志，方便后续接入 Trace 或前端 Thinking 面板。"""

        entry = {
            "tool": self.name,
            "success": success,
            "latency_ms": latency_ms,
            "attempt": attempt,
            "source": source,
            "error": error,
            "timestamp": time.time(),
        }
        self.call_log.append(entry)
        # 底层还是调用的 `TraceRecorder`
        record_trace_event("tool_call", entry)
        if success:
            logger.info("%s success source=%s latency=%sms", self.name, source, latency_ms)
        else:
            logger.warning("%s failed attempt=%s error=%s", self.name, attempt, error)

    def _cache_result(
        self,
        *,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        data: Any,
        source: str,
    ) -> None:
        """把工具结果摘要写入 ToolCache。

        完整数据只在可 JSON 序列化且体积可控时写入摘要；prompt 侧只通过 evidence_ref
        引用缓存，不直接塞完整结果。
        """

        if self.name.startswith("llm."):
            return
        try:
            request = {"args": _compact_value(args), "kwargs": _compact_value(kwargs)}
            request_hash = make_request_hash(request)
            cache_key = make_cache_key(self.name, request)
            ttl = ttl_seconds_for_tool(self.name)
            result_summary = _result_summary(data)
            FileMemoryStore().put_tool_cache({
                "cache_key": cache_key,
                "tool_name": self.name,
                "request_hash": request_hash,
                "result_summary": result_summary,
                "full_result_path": "",
                "source": source,
                "fetched_at": _now_iso(),
                "expires_at": expires_at_from_ttl(ttl),
                "confidence": 1.0 if source == "live" else 0.55,
                "fallback_used": source == "fallback",
            })
            record_trace_event(
                "tool_cache_put",
                {
                    "tool_name": self.name,
                    "cache_key": cache_key,
                    "expires_at": expires_at_from_ttl(ttl),
                    "fallback_used": source == "fallback",
                },
            )
        except Exception as exc:  # noqa: BLE001 - 缓存失败不能影响主工具调用。
            record_trace_event("tool_cache_failed", {"tool_name": self.name, "error": str(exc)})


def _redact_request(request: ToolCallRequest) -> dict[str, Any]:
    """Trace 中只记录治理相关摘要，不记录完整敏感参数。"""

    params = request.params
    return {
        "tool_name": request.tool_name,
        "risk_level": request.risk_level,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "task_id": request.task_id,
        "idempotency_key": request.idempotency_key,
        "requires_confirmation": request.requires_confirmation,
        "param_keys": sorted(params.keys()),
        "target_id": params.get("target_id") or params.get("poi_id"),
    }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _compact_value(value: Any) -> Any:
    """把工具请求参数压缩到可缓存摘要。"""

    if isinstance(value, dict):
        return {
            str(key): _compact_value(item)
            for key, item in value.items()
            if str(key).lower() not in {"api_key", "password", "token"}
        }
    if isinstance(value, (list, tuple)):
        return [_compact_value(item) for item in list(value)[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _result_summary(data: Any) -> dict[str, Any]:
    """生成工具结果摘要，避免缓存和 trace 过大。"""

    if isinstance(data, dict):
        return {
            "type": "dict",
            "keys": sorted(str(key) for key in data.keys())[:30],
            "counts": {
                str(key): len(value) for key, value in data.items() if isinstance(value, list)
            },
        }
    if isinstance(data, list):
        return {"type": "list", "count": len(data), "sample": _compact_value(data[:3])}
    return {"type": type(data).__name__, "preview": str(data)[:300]}
