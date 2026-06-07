from __future__ import annotations

from dataclasses import dataclass


DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60
DEFAULT_PLAN_STATE_TTL_SECONDS = 2 * 60 * 60
DEFAULT_IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class MemoryRedisKey:
    key: str
    ttl_seconds: int | None


class MemoryRedisKeys:
    """Key naming for volatile memory data; no Redis client dependency here."""

    namespace = "liferoute:memory"

    @classmethod
    def session_context(cls, session_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(
            f"{cls.namespace}:session:{_safe(session_id)}:context",
            DEFAULT_SESSION_TTL_SECONDS,
        )

    @classmethod
    def recent_turns(cls, session_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(
            f"{cls.namespace}:session:{_safe(session_id)}:recent_turns",
            DEFAULT_SESSION_TTL_SECONDS,
        )

    @classmethod
    def plan_state(cls, task_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(
            f"{cls.namespace}:plan_state:{_safe(task_id)}",
            DEFAULT_PLAN_STATE_TTL_SECONDS,
        )

    @classmethod
    def user_profile_snapshot(cls, user_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(
            f"{cls.namespace}:user:{_safe(user_id)}:profile_snapshot",
            DEFAULT_SESSION_TTL_SECONDS,
        )

    @classmethod
    def similar_profile_cache(cls, user_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(
            f"{cls.namespace}:user:{_safe(user_id)}:similar_profiles",
            DEFAULT_SESSION_TTL_SECONDS,
        )

    @classmethod
    def event_idempotency(cls, event_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(
            f"{cls.namespace}:event:{_safe(event_id)}:seen",
            DEFAULT_IDEMPOTENCY_TTL_SECONDS,
        )

    @classmethod
    def event_retry(cls, event_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(
            f"{cls.namespace}:event:{_safe(event_id)}:retry",
            DEFAULT_IDEMPOTENCY_TTL_SECONDS,
        )

    @classmethod
    def user_lock(cls, user_id: str) -> MemoryRedisKey:
        return MemoryRedisKey(f"{cls.namespace}:lock:user:{_safe(user_id)}", 30)


def _safe(value: str | None) -> str:
    raw = str(value or "default").strip() or "default"
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw)
    return safe[:128] or "default"
