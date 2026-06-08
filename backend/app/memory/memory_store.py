from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol, TypedDict

from app.runtime.runtime_paths import MEMORY_DIR, SESSIONS_DIR, TOOL_CACHE_DIR
from app.runtime.runtime_store import get_runtime_store


class UserProfileMemory(TypedDict, total=False):
    """长期用户画像记忆。"""

    preferred_city: str
    common_origins: list[dict[str, Any]]
    diet_preferences: list[str]
    children: list[dict[str, Any]]
    budget_habit: dict[str, Any]
    disliked_keywords: list[str]
    favorite_categories: dict[str, int]
    updated_at: str


class SessionMemory(TypedDict, total=False):
    """会话内规划记忆。"""

    session_id: str
    active_task_id: str | None
    rejected_plans: list[dict[str, Any]]
    selected_plan_id: str | None
    recent_revisions: list[dict[str, Any]]
    conversation_summary: dict[str, Any]


class ToolCacheEntry(TypedDict, total=False):
    """工具结果缓存条目。"""

    cache_key: str
    tool_name: str
    request_hash: str
    result_summary: dict[str, Any]
    full_result_path: str
    source: str
    fetched_at: str
    expires_at: str
    confidence: float
    fallback_used: bool


class MemoryStore(Protocol):
    """三层记忆统一接口。"""

    def load_user_profile(self, user_id: str) -> UserProfileMemory: ...

    def update_user_profile(
        self, user_id: str, patch: dict[str, Any], source_event: str
    ) -> None: ...

    def load_session(self, session_id: str) -> SessionMemory: ...

    def append_session_event(self, session_id: str, event: dict[str, Any]) -> None: ...

    def get_tool_cache(self, key: str) -> ToolCacheEntry | None: ...

    def put_tool_cache(self, entry: ToolCacheEntry) -> None: ...

    def search_relevant_memory(
        self, query: str, user_id: str, limit: int
    ) -> list[dict[str, Any]]: ...


class FileMemoryStore:
    """文件型 MemoryStore，实现长期画像、会话记忆和工具缓存。

    这是 v1 的可审计实现；后续迁移数据库时保持接口不变即可。
    """

    def __init__(self) -> None:
        self.profile_path = MEMORY_DIR / "user_profile_v2.json"
        if not self.profile_path.exists():
            self.profile_path.write_text(
                json.dumps(_empty_user_profile(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def load_user_profile(self, user_id: str) -> UserProfileMemory:
        """读取长期用户画像。"""

        del user_id
        data = _read_json(self.profile_path, _empty_user_profile())
        return data if isinstance(data, dict) else _empty_user_profile()

    def update_user_profile(
        self,
        user_id: str,
        patch: dict[str, Any],
        source_event: str,
    ) -> None:
        """合并写入长期画像，并记录来源。"""

        del user_id
        profile = self.load_user_profile(user_id="default")
        for key, value in patch.items():
            if isinstance(value, list):
                profile[key] = _dedupe([*profile.get(key, []), *value])
            elif isinstance(value, dict) and isinstance(profile.get(key), dict):
                profile[key] = {**profile.get(key, {}), **value}
            else:
                profile[key] = value
        profile["updated_at"] = _now_iso()
        profile.setdefault("sources", []).append({"source_event": source_event, "at": _now_iso()})
        self.profile_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def load_session(self, session_id: str) -> SessionMemory:
        """读取会话内规划记忆。"""

        path = _session_memory_path(session_id)
        if not path.exists():
            return _empty_session(session_id)
        data = _read_json(path, _empty_session(session_id))
        return data if isinstance(data, dict) else _empty_session(session_id)

    def append_session_event(self, session_id: str, event: dict[str, Any]) -> None:
        """追加会话事件，并更新派生字段。"""

        memory = self.load_session(session_id)
        events = memory.setdefault("events", [])
        event = {**event, "created_at": event.get("created_at") or _now_iso()}
        events.append(event)
        if event.get("type") == "plan_rejected":
            memory.setdefault("rejected_plans", []).append({
                "plan_id": event.get("plan_id"),
                "reason": event.get("reason", ""),
                "rejected_at": event["created_at"],
            })
        if event.get("type") == "plan_selected":
            memory["selected_plan_id"] = event.get("plan_id")
            memory["last_selected_plan_summary"] = event.get("plan_summary", {})
        if event.get("type") == "revision":
            memory.setdefault("recent_revisions", []).append({
                "query": event.get("query", ""),
                "parsed_patch": event.get("parsed_patch", {}),
                "created_at": event["created_at"],
            })
            memory["recent_revisions"] = memory["recent_revisions"][-8:]
        memory["conversation_summary"] = _derive_conversation_summary(memory)
        _session_memory_path(session_id).write_text(
            json.dumps(memory, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def get_tool_cache(self, key: str) -> ToolCacheEntry | None:
        """读取未过期的工具缓存。过期返回 None，但文件保留用于历史解释。"""

        data = get_runtime_store().get_tool_cache(key)
        return data if isinstance(data, dict) else None

    def put_tool_cache(self, entry: ToolCacheEntry) -> None:
        """写入工具缓存。"""

        key = entry.get("cache_key") or make_cache_key(
            str(entry.get("tool_name", "")),
            entry.get("request_hash", {}),
        )
        entry["cache_key"] = key
        get_runtime_store().put_tool_cache(key, entry)

    def search_relevant_memory(
        self,
        query: str,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """关键词 fallback 检索长期画像和会话摘要。"""

        profile = self.load_user_profile(user_id)
        hits: list[dict[str, Any]] = []
        text = json.dumps(profile, ensure_ascii=False)
        for token in _tokens(query):
            if token and token in text:
                hits.append({"type": "user_profile", "text": text[:500], "score": 0.6})
                break
        for path in sorted(SESSIONS_DIR.glob("*.memory.json"))[-20:]:
            data = _read_json(path, {})
            payload = json.dumps(data.get("conversation_summary", data), ensure_ascii=False)
            if any(token in payload for token in _tokens(query)):
                hits.append({"type": "session", "text": payload[:500], "score": 0.5})
        return hits[:limit]


def make_cache_key(tool_name: str, request: Any) -> str:
    """生成稳定工具缓存 key。"""

    raw = json.dumps({"tool_name": tool_name, "request": request}, sort_keys=True, default=str)
    return "cache_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def make_request_hash(request: Any) -> str:
    """生成工具请求 hash，用于幂等和缓存。"""

    raw = json.dumps(request, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def ttl_seconds_for_tool(tool_name: str) -> int:
    """工具 TTL 策略。"""

    lowered = tool_name.lower()
    if any(key in lowered for key in ("route", "poi", "restaurant_search", "activity_search")):
        return 12 * 60 * 60
    if any(key in lowered for key in ("weather", "inventory", "stock", "queue", "availability")):
        return 15 * 60
    return 60 * 60


def expires_at_from_ttl(ttl_seconds: int) -> str:
    """根据 TTL 生成过期时间。"""

    return _iso_from_ts(time.time() + ttl_seconds)


def _empty_user_profile() -> UserProfileMemory:
    return {
        "preferred_city": "",
        "common_origins": [],
        "diet_preferences": [],
        "children": [],
        "budget_habit": {"level": "mid", "avg_per_person": 0},
        "disliked_keywords": [],
        "favorite_categories": {},
        "updated_at": "",
    }


def _empty_session(session_id: str) -> SessionMemory:
    return {
        "session_id": session_id,
        "active_task_id": None,
        "rejected_plans": [],
        "selected_plan_id": None,
        "recent_revisions": [],
        "conversation_summary": {},
        "events": [],
    }


def _session_memory_path(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in {"_", "-"})
    return SESSIONS_DIR / f"{safe}.memory.json"


def _tool_cache_path(key: str) -> Path:
    safe = "".join(ch for ch in key if ch.isalnum() or ch in {"_", "-"})
    return TOOL_CACHE_DIR / f"{safe}.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return default


def _derive_conversation_summary(memory: SessionMemory) -> dict[str, Any]:
    return {
        "active_task_id": memory.get("active_task_id"),
        "selected_plan_id": memory.get("selected_plan_id"),
        "rejected_plan_count": len(memory.get("rejected_plans", []) or []),
        "recent_revisions": memory.get("recent_revisions", [])[-5:],
    }


def _now_iso() -> str:
    return _iso_from_ts(time.time())


def _iso_from_ts(value: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def _parse_ts(value: str) -> float | None:
    try:
        return time.mktime(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except TypeError, ValueError:
        return None


def _tokens(query: str) -> list[str]:
    return [token for token in query.replace("，", " ").replace(",", " ").split() if token]


def _dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
