from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, TypeVar


logger = logging.getLogger("liferoute.tool_harness")

T = TypeVar("T")


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
    """

    name: str
    timeout_seconds: float = 10
    max_retries: int = 1
    retry_backoff_seconds: float = 0.2
    fallback: Callable[..., T] | None = None
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> HarnessResult:
        """执行同步工具函数，并返回标准化结果。"""

        last_error: str | None = None
        for attempt in range(1, self.max_retries + 2):
            started = time.perf_counter()
            try:
                data = self._run_with_timeout(fn, *args, **kwargs)
                latency = int((time.perf_counter() - started) * 1000)
                self._record(True, latency, attempt, "live", None)
                return HarnessResult(
                    success=True,
                    data=data,
                    source="live",
                    latency_ms=latency,
                    attempts=attempt,
                )
            except Exception as exc:  # noqa: BLE001 - Harness 必须吞掉所有工具异常并转成结构化结果。
                last_error = str(exc)
                latency = int((time.perf_counter() - started) * 1000)
                self._record(False, latency, attempt, "live", last_error)
                if attempt <= self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)

        if self.fallback:
            fallback_started = time.perf_counter()
            try:
                data = self.fallback(*args, **kwargs)
                latency = int((time.perf_counter() - fallback_started) * 1000)
                self._record(True, latency, -1, "fallback", None)
                return HarnessResult(
                    success=True,
                    data=data,
                    source="fallback",
                    latency_ms=latency,
                    attempts=self.max_retries + 1,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"{last_error}; fallback failed: {exc}" if last_error else str(exc)
                self._record(False, 0, -1, "fallback", str(exc))

        return HarnessResult(
            success=False,
            error=last_error,
            source="failed",
            attempts=self.max_retries + 1,
        )

    def _run_with_timeout(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """用线程池为同步函数加超时控制。"""

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn, *args, **kwargs)
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
        if success:
            logger.info("%s success source=%s latency=%sms", self.name, source, latency_ms)
        else:
            logger.warning("%s failed attempt=%s error=%s", self.name, attempt, error)

