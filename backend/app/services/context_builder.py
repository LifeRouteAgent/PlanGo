from __future__ import annotations

from typing import Any


class ContextBuilder:
    """上下文分层构建器。

    LLM 只接收必要摘要：当前任务、压缩记忆和少量状态统计。完整 POI、Trace 和历史文件不进入 prompt。
    """

    def build_user_profile_context(self, user_profile: dict[str, Any]) -> dict[str, Any]:
        """构建给 Intent/Planner 使用的用户画像上下文。"""

        memory_context = user_profile.get("memory_context", {})
        memory_profile = user_profile.get("memory_profile", {})
        return {
            "preferred_city": (
                user_profile.get("preferred_city") or memory_profile.get("preferred_city")
            ),
            "preferred_areas": _safe_list(
                user_profile.get("preferred_areas") or memory_profile.get("preferred_areas")
            ),
            "indoor_preference": bool(
                user_profile.get("indoor_preference") or memory_profile.get("indoor_preference")
            ),
            "disliked_keywords": _safe_list(
                user_profile.get("disliked_keywords") or memory_profile.get("disliked_keywords")
            )[:8],
            "favorite_categories": _top_mapping(
                memory_profile.get("favorite_categories", {}), limit=6
            ),
            "memory_context": {
                "profile_summary": memory_context.get("profile_summary", ""),
                "snippets": _safe_list(memory_context.get("snippets"))[:5],
                "memory_fit_tags": _safe_list(memory_context.get("memory_fit_tags"))[:12],
                "source": memory_context.get("source", "none"),
            },
            "similar_user_preferences": _safe_list(user_profile.get("similar_user_preferences"))[
                :3
            ],
            "profile_cluster": user_profile.get("profile_cluster", {}),
        }

    def build_state_context(self, state: dict[str, Any]) -> dict[str, Any]:
        """构建给 Response/Planner 使用的当前状态摘要。"""

        return {
            "user_query": state.get("user_query", ""),
            "intent_type": state.get("intent_type", ""),
            "answer_mode": state.get("answer_mode", ""),
            "constraints": _public_constraints(state.get("constraints", {})),
            "dag_plan": _public_dag_plan(state.get("dag_plan", {})),
            "candidate_counts": _count_mapping(state.get("candidate_pois", {})),
            "recommended_counts": _count_mapping(state.get("recommended_pois", {})),
            "plan_count": len(state.get("ranked_plans", []) or []),
            "error_count": len(state.get("errors", []) or []),
            "memory_context": (
                self.build_user_profile_context(state.get("user_profile", {})).get(
                    "memory_context", {}
                )
            ),
        }


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _top_mapping(value: Any, *, limit: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = sorted(value, key=value.get, reverse=True)[:limit]
    return {key: value[key] for key in keys}


def _count_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): len(items) if isinstance(items, list) else 0 for key, items in value.items()}


def _public_constraints(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "city",
        "scenario",
        "people_count",
        "preferences",
        "location_area",
        "start_time",
        "duration_hours",
        "budget",
        "indoor_preferred",
        "avoid_tags",
        "excluded_keywords",
        "max_route_minutes",
    }
    return {key: value.get(key) for key in allowed if value.get(key) not in (None, "", [])}


def _public_dag_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "planning_template",
        "required_slots",
        "slot_sequence",
        "time_budget",
        "movement_policy",
        "candidate_strategy",
        "enabled_skills",
    }
    return {key: value.get(key) for key in allowed if value.get(key) not in (None, "", [])}
