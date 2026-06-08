from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, TypedDict

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings
from app.runtime.runtime_paths import (
    SESSIONS_DIR,
    TASKS_DIR,
    TOOL_CACHE_DIR,
    TRACES_DIR,
    ensure_runtime_dirs,
)


class NodeMetricRecord(TypedDict, total=False):
    trace_id: str
    run_id: str
    session_id: str
    node_name: str
    started_at: float
    ended_at: float
    duration_ms: int
    status: str
    error: str | None
    output_summary: dict[str, Any]


class RuntimeStore(Protocol):
    """运行态存储接口。

    这个接口覆盖生产运行最关键的五类状态：session、checkpoint、tool cache、
    trace event 和 node metric。上层服务不再直接关心 MySQL 或文件落盘细节。
    """

    def load_session(self, session_id: str) -> dict[str, Any] | None: ...

    def save_session(self, session_id: str, payload: dict[str, Any]) -> None: ...

    def load_task(self, task_id: str) -> dict[str, Any] | None: ...

    def save_task(self, task_id: str, payload: dict[str, Any]) -> None: ...

    def list_tasks(self) -> list[dict[str, Any]]: ...

    def get_tool_cache(self, key: str) -> dict[str, Any] | None: ...

    def put_tool_cache(self, key: str, payload: dict[str, Any]) -> None: ...

    def append_trace_event(self, trace_id: str, event: dict[str, Any]) -> None: ...

    def read_trace_events(self, trace_id: str) -> list[dict[str, Any]]: ...

    def record_node_metric(self, metric: NodeMetricRecord) -> None: ...

    def list_node_metrics(self, trace_id: str | None = None) -> list[NodeMetricRecord]: ...

    def health(self) -> dict[str, Any]: ...


class FileRuntimeStore(RuntimeStore):
    """文件型 runtime fallback。"""

    def __init__(self) -> None:
        ensure_runtime_dirs()

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        return _read_json(_session_path(session_id))

    def save_session(self, session_id: str, payload: dict[str, Any]) -> None:
        _write_json(_session_path(session_id), payload)

    def load_task(self, task_id: str) -> dict[str, Any] | None:
        return _read_json(_task_path(task_id))

    def save_task(self, task_id: str, payload: dict[str, Any]) -> None:
        _write_json(_task_path(task_id), payload)

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for path in TASKS_DIR.glob("task_*.json"):
            payload = _read_json(path)
            if isinstance(payload, dict):
                tasks.append(payload)
        return tasks

    def get_tool_cache(self, key: str) -> dict[str, Any] | None:
        payload = _read_json(_tool_cache_path(key))
        if not isinstance(payload, dict) or _is_expired(payload.get("expires_at")):
            return None
        return payload

    def put_tool_cache(self, key: str, payload: dict[str, Any]) -> None:
        _write_json(_tool_cache_path(key), {**payload, "cache_key": key})

    def append_trace_event(self, trace_id: str, event: dict[str, Any]) -> None:
        path = TRACES_DIR / f"{_safe_name(trace_id)}.jsonl"
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def read_trace_events(self, trace_id: str) -> list[dict[str, Any]]:
        path = TRACES_DIR / f"{_safe_name(trace_id)}.jsonl"
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
            except json.JSONDecodeError:
                continue
        return events

    def record_node_metric(self, metric: NodeMetricRecord) -> None:
        trace_id = str(metric.get("trace_id") or "unknown")
        path = TRACES_DIR / f"{_safe_name(trace_id)}.metrics.jsonl"
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(metric, ensure_ascii=False, default=str) + "\n")

    def list_node_metrics(self, trace_id: str | None = None) -> list[NodeMetricRecord]:
        paths = (
            [TRACES_DIR / f"{_safe_name(trace_id)}.metrics.jsonl"]
            if trace_id
            else list(TRACES_DIR.glob("*.metrics.jsonl"))
        )
        result: list[NodeMetricRecord] = []
        for path in paths:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        result.append(payload)
                except json.JSONDecodeError:
                    continue
        return sorted(result, key=lambda item: int(item.get("duration_ms", 0) or 0), reverse=True)

    def health(self) -> dict[str, Any]:
        return {"store": "file", "ok": True, "fallback": False}


class MySqlRuntimeStore(RuntimeStore):
    """MySQL runtime 主存储。"""

    def __init__(self) -> None:
        self._conn_kwargs = {
            "host": settings.database_host,
            "port": settings.database_port,
            "user": settings.database_user,
            "password": settings.database_password,
            "database": settings.database_name,
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": True,
            "connect_timeout": 1,
            "read_timeout": 5,
            "write_timeout": 5,
        }
        self._check_connection()

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._fetch_one(
            "SELECT payload FROM runtime_sessions WHERE session_id=%s", session_id
        )
        return _loads_payload(row["payload"]) if row else None

    def save_session(self, session_id: str, payload: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO runtime_sessions(session_id, payload, updated_at)
            VALUES(%s, %s, NOW())
            ON DUPLICATE KEY UPDATE payload=VALUES(payload), updated_at=NOW()
            """,
            session_id,
            _dumps_payload(payload),
        )

    def load_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._fetch_one("SELECT payload FROM runtime_tasks WHERE task_id=%s", task_id)
        return _loads_payload(row["payload"]) if row else None

    def save_task(self, task_id: str, payload: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO runtime_tasks(task_id, session_id, status, version, state_revision, payload, updated_at)
            VALUES(%s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
              session_id=VALUES(session_id),
              status=VALUES(status),
              version=VALUES(version),
              state_revision=VALUES(state_revision),
              payload=VALUES(payload),
              updated_at=NOW()
            """,
            task_id,
            str(payload.get("session_id") or ""),
            str(payload.get("status") or ""),
            int(payload.get("version", 1) or 1),
            int(payload.get("state_revision", 0) or 0),
            _dumps_payload(payload),
        )

    def list_tasks(self) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            "SELECT payload FROM runtime_tasks ORDER BY updated_at DESC LIMIT 500"
        )
        return [
            payload for row in rows if isinstance((payload := _loads_payload(row["payload"])), dict)
        ]

    def get_tool_cache(self, key: str) -> dict[str, Any] | None:
        row = self._fetch_one(
            "SELECT payload, expires_at FROM runtime_tool_cache WHERE cache_key=%s",
            key,
        )
        if not row or _is_expired(row.get("expires_at")):
            return None
        return _loads_payload(row["payload"])

    def put_tool_cache(self, key: str, payload: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO runtime_tool_cache(cache_key, tool_name, request_hash, payload, expires_at, updated_at)
            VALUES(%s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
              tool_name=VALUES(tool_name),
              request_hash=VALUES(request_hash),
              payload=VALUES(payload),
              expires_at=VALUES(expires_at),
              updated_at=NOW()
            """,
            key,
            str(payload.get("tool_name") or ""),
            str(payload.get("request_hash") or ""),
            _dumps_payload({**payload, "cache_key": key}),
            _mysql_dt(payload.get("expires_at")),
        )

    def append_trace_event(self, trace_id: str, event: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO runtime_trace_events(trace_id, run_id, session_id, event_type, payload, created_at)
            VALUES(%s, %s, %s, %s, %s, FROM_UNIXTIME(%s))
            """,
            trace_id,
            str(event.get("run_id") or ""),
            str(event.get("session_id") or ""),
            str(event.get("event_type") or ""),
            _dumps_payload(event),
            float(event.get("timestamp") or time.time()),
        )

    def read_trace_events(self, trace_id: str) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            "SELECT payload FROM runtime_trace_events WHERE trace_id=%s ORDER BY id ASC",
            trace_id,
        )
        return [
            payload for row in rows if isinstance((payload := _loads_payload(row["payload"])), dict)
        ]

    def record_node_metric(self, metric: NodeMetricRecord) -> None:
        self._execute(
            """
            INSERT INTO runtime_node_metrics(
              trace_id, run_id, session_id, node_name, started_at, ended_at,
              duration_ms, status, error, output_summary, created_at
            )
            VALUES(%s, %s, %s, %s, FROM_UNIXTIME(%s), FROM_UNIXTIME(%s), %s, %s, %s, %s, NOW())
            """,
            str(metric.get("trace_id") or ""),
            str(metric.get("run_id") or ""),
            str(metric.get("session_id") or ""),
            str(metric.get("node_name") or ""),
            float(metric.get("started_at") or time.time()),
            float(metric.get("ended_at") or time.time()),
            int(metric.get("duration_ms", 0) or 0),
            str(metric.get("status") or "success"),
            metric.get("error"),
            _dumps_payload(metric.get("output_summary") or {}),
        )

    def list_node_metrics(self, trace_id: str | None = None) -> list[NodeMetricRecord]:
        if trace_id:
            rows = self._fetch_all(
                """
                SELECT trace_id, run_id, session_id, node_name,
                       UNIX_TIMESTAMP(started_at) AS started_ts,
                       UNIX_TIMESTAMP(ended_at) AS ended_ts,
                       duration_ms, status, error, output_summary
                FROM runtime_node_metrics
                WHERE trace_id=%s
                ORDER BY duration_ms DESC
                """,
                trace_id,
            )
        else:
            rows = self._fetch_all("""
                SELECT trace_id, run_id, session_id, node_name,
                       UNIX_TIMESTAMP(started_at) AS started_ts,
                       UNIX_TIMESTAMP(ended_at) AS ended_ts,
                       duration_ms, status, error, output_summary
                FROM runtime_node_metrics
                ORDER BY created_at DESC
                LIMIT 500
                """)
        return [_metric_from_row(row) for row in rows]

    def health(self) -> dict[str, Any]:
        self._check_connection()
        return {"store": "mysql", "ok": True, "fallback": False}

    def _check_connection(self) -> None:
        with pymysql.connect(**self._conn_kwargs) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")

    def _execute(self, sql: str, *args: Any) -> None:
        with pymysql.connect(**self._conn_kwargs) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, args)

    def _fetch_one(self, sql: str, *args: Any) -> dict[str, Any] | None:
        with pymysql.connect(**self._conn_kwargs) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, args)
                return cursor.fetchone()

    def _fetch_all(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        with pymysql.connect(**self._conn_kwargs) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, args)
                return list(cursor.fetchall())


class ResilientRuntimeStore(RuntimeStore):
    """MySQL 优先、文件 fallback 的运行态存储。

    每个方法显式声明而非依赖 __getattr__ 动态派发，保证 IDE 自动补全和静态类型检查。
    """

    def __init__(
        self, primary: RuntimeStore | None, fallback: RuntimeStore, primary_error: str = ""
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self.primary_error = primary_error

    def _delegate(self, method_name: str, *args: Any) -> Any:
        """先尝试 primary，失败则使用 fallback。"""
        if self._primary is not None:
            try:
                return getattr(self._primary, method_name)(*args)
            except Exception as exc:  # noqa: BLE001 - runtime 层必须保证 demo 可降级运行。
                self.primary_error = str(exc)
        return getattr(self._fallback, method_name)(*args)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        return self._delegate("load_session", session_id)

    def save_session(self, session_id: str, payload: dict[str, Any]) -> None:
        return self._delegate("save_session", session_id, payload)

    def load_task(self, task_id: str) -> dict[str, Any] | None:
        return self._delegate("load_task", task_id)

    def save_task(self, task_id: str, payload: dict[str, Any]) -> None:
        return self._delegate("save_task", task_id, payload)

    def list_tasks(self) -> list[dict[str, Any]]:
        return self._delegate("list_tasks")

    def get_tool_cache(self, key: str) -> dict[str, Any] | None:
        return self._delegate("get_tool_cache", key)

    def put_tool_cache(self, key: str, payload: dict[str, Any]) -> None:
        return self._delegate("put_tool_cache", key, payload)

    def append_trace_event(self, trace_id: str, event: dict[str, Any]) -> None:
        return self._delegate("append_trace_event", trace_id, event)

    def read_trace_events(self, trace_id: str) -> list[dict[str, Any]]:
        return self._delegate("read_trace_events", trace_id)

    def record_node_metric(self, metric: NodeMetricRecord) -> None:
        return self._delegate("record_node_metric", metric)

    def list_node_metrics(self, trace_id: str | None = None) -> list[NodeMetricRecord]:
        return self._delegate("list_node_metrics", trace_id)

    def health(self) -> dict[str, Any]:
        if self._primary is not None:
            try:
                primary_health = self._primary.health()
                return {**primary_health, "fallback_available": True}
            except Exception as exc:  # noqa: BLE001
                self.primary_error = str(exc)
        return {
            "store": "file",
            "ok": True,
            "fallback": True,
            "primary_error": self.primary_error,
        }


@lru_cache(maxsize=1)
def get_runtime_store() -> RuntimeStore:
    """获取全局 runtime store。"""

    fallback = FileRuntimeStore()
    if settings.runtime_store.lower() != "mysql" or not settings.runtime_mysql_enabled:
        return fallback
    try:
        return ResilientRuntimeStore(MySqlRuntimeStore(), fallback)
    except Exception as exc:  # noqa: BLE001
        return ResilientRuntimeStore(None, fallback, primary_error=str(exc))


def _safe_name(value: str | None) -> str:
    raw = str(value or "default")
    return "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-"}) or "default"


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{_safe_name(session_id)}.json"


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{_safe_name(task_id)}.json"


def _tool_cache_path(key: str) -> Path:
    return TOOL_CACHE_DIR / f"{_safe_name(key)}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except OSError, json.JSONDecodeError:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _dumps_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _loads_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        data = json.loads(str(payload or "{}"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _is_expired(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, (int, float)):
        return float(value) < time.time()
    text = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(text, fmt)) < time.time()
        except ValueError:
            continue
    return False


def _mysql_dt(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z") and "T" in text:
        return text.replace("T", " ").replace("Z", "")
    return text


def _metric_from_row(row: dict[str, Any]) -> NodeMetricRecord:
    return {
        "trace_id": str(row.get("trace_id") or ""),
        "run_id": str(row.get("run_id") or ""),
        "session_id": str(row.get("session_id") or ""),
        "node_name": str(row.get("node_name") or ""),
        "started_at": float(row.get("started_ts") or 0),
        "ended_at": float(row.get("ended_ts") or 0),
        "duration_ms": int(row.get("duration_ms", 0) or 0),
        "status": str(row.get("status") or "success"),
        "error": row.get("error"),
        "output_summary": _loads_payload(row.get("output_summary")),
    }
