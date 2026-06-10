from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, List, Dict, Tuple


@dataclass
class ContextSnapshot:
    """每次 LLM 调用使用的结构化上下文快照。

    该结构是 prompt 的唯一来源，避免把完整聊天历史、完整工具返回或全部候选 POI
    直接塞进 prompt。完整数据仍保留在 PlanState、ToolCache 和 Trace 中。
    """

    current_intent: dict[str, Any]
    user_constraints: dict[str, Any]
    planning_state: dict[str, Any]
    tool_evidence: list[dict[str, Any]]
    conversation_summary: dict[str, Any]
    poi_knowledge: dict[str, Any]
    prompt_meta: dict[str, Any]


class ContextBuilder:
    """上下文分层构建器。

    LLM 只接收必要摘要：当前任务、压缩记忆和少量状态统计。完整 POI、Trace 和历史文件不进入 prompt。
    """

    @staticmethod
    def build_user_profile_context(user_profile: dict[str, Any]) -> dict[str, Any]:
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

    @staticmethod
    def build_for(
        agent_name: str,
        state: dict[str, Any],
        *,
        token_budget: int = 3000,
        top_k_per_category: int = 8,
    ) -> ContextSnapshot:
        """为指定 Agent 构建可控、可裁剪的 prompt 上下文。

        硬约束永不裁剪；候选 POI 和工具证据只保留 top-k/摘要字段；聊天历史仅以会话摘要
        的形式进入上下文。后续所有 LLM Agent 应优先使用该方法，而不是自行拼接历史。
        """

        constraints = state.get("constraints", {})
        candidate_summary, clipped_fields1 = _top_k_pois_by_category(
            state.get("candidate_pois", {}), top_k_per_category, "candidate_pois"
        )
        recommended_summary, clipped_fields2 = _top_k_pois_by_category(
            state.get("recommended_pois", {}),
            top_k_per_category,
            "recommended_pois",
        )

        tool_evidence, clipped_fields3 = _tool_evidence(state, top_k=12)
        evidence_refs = [
            item.get("evidence_ref") for item in tool_evidence if item.get("evidence_ref")
        ]
        return ContextSnapshot(
            current_intent={
                "intent_type": state.get("intent_type"),
                "answer_mode": state.get("answer_mode"),
                "target_categories": state.get("target_categories", []),
                "must_pois": constraints.get("must_pois", []),
                "activity_intents": constraints.get("activity_intents", []),
                "revision_id": state.get("revision_id", ""),
                "is_revision": state.get("is_revision", False),
            },
            user_constraints={
                "hard_constraints": _hard_constraints(constraints, state),
                "soft_preferences": _soft_preferences(constraints, state),
                "negative_constraints": _negative_constraints(constraints),
            },
            planning_state={
                "dag_plan": _public_dag_plan(state.get("dag_plan", {})),
                "candidate_summary": candidate_summary,
                "recommended_summary": recommended_summary,
                "ranked_plan_count": len(state.get("ranked_plans", []) or []),
                "selected_plan_id": (state.get("selected_plan") or {}).get("id", ""),
                "current_phase": _infer_current_phase(state),
                "errors": _public_issues(state.get("errors", []), limit=8),
            },
            tool_evidence=tool_evidence,
            conversation_summary=_conversation_summary(state),
            poi_knowledge=(
                state.get("poi_knowledge", {})
                if isinstance(state.get("poi_knowledge"), dict)
                else {}
            ),
            prompt_meta={
                "agent_name": agent_name,
                "token_budget": token_budget,
                "top_k_per_category": top_k_per_category,
                "clipped_fields": clipped_fields1 + clipped_fields2 + clipped_fields3,
                "evidence_refs": evidence_refs,
                "built_at": int(time.time()),
            },
        )

    @staticmethod
    def merge_revision_into_intent(
        previous_intent: dict[str, Any], revision: dict[str, Any]
    ) -> dict[str, Any]:
        """把多轮需求变更合并到当前 intent。

        新输入覆盖同类软约束；明确排除项追加；硬约束冲突不直接覆盖，而是写入
        `conflicts` 交给 Clarifier 追问。
        """

        if any(
            key in previous_intent
            for key in ("hard_constraints", "soft_preferences", "negative_constraints")
        ):
            hard = dict(previous_intent.get("hard_constraints", {}) or {})
            soft = dict(previous_intent.get("soft_preferences", {}) or {})
            negative = dict(previous_intent.get("negative_constraints", {}) or {})
            conflicts: list[dict[str, Any]] = []
            revision_hard = revision.get("hard_constraints", {}) or {}
            revision_soft = revision.get("soft_preferences", {}) or {}
            revision_negative = revision.get("negative_constraints", {}) or {}
            for key, new_value in revision_hard.items():
                if new_value in (None, "", []):
                    continue
                old_value = hard.get(key)
                if old_value not in (None, "", [], new_value):
                    conflicts.append({"field": key, "previous": old_value, "revision": new_value})
                else:
                    hard[key] = new_value
            for key, new_value in revision_soft.items():
                if new_value not in (None, "", []):
                    soft[key] = new_value
            for key in ("excluded_keywords", "avoid_tags", "must_not_pois"):
                negative[key] = _dedupe(
                    [*_safe_list(negative.get(key)), *_safe_list(revision_negative.get(key))]
                )
            return {
                **previous_intent,
                "hard_constraints": hard,
                "soft_preferences": soft,
                "negative_constraints": negative,
                "conflicts": conflicts,
            }

        merged = dict(previous_intent or {})
        conflicts: list[dict[str, Any]] = []
        for key in ("intent_type", "target_categories", "activity_intents", "preferences"):
            if revision.get(key) not in (None, "", []):
                merged[key] = revision[key]
        for key in ("people_count", "start_time", "duration_hours", "budget"):
            old_value = merged.get(key)
            new_value = revision.get(key)
            if new_value in (None, "", []):
                continue
            if old_value not in (None, "", [], new_value):
                conflicts.append({"field": key, "previous": old_value, "revision": new_value})
            else:
                merged[key] = new_value
        merged["excluded_keywords"] = _dedupe([
            *_safe_list(merged.get("excluded_keywords")),
            *_safe_list(revision.get("excluded_keywords")),
        ])
        merged["must_not_pois"] = _dedupe(
            [*_safe_list(merged.get("must_not_pois")), *_safe_list(revision.get("must_not_pois"))]
        )
        merged["conflicts"] = conflicts
        return merged


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
        "dynamic_slots",
        "time_budget",
        "movement_policy",
        "candidate_strategy",
    }
    return {key: value.get(key) for key in allowed if value.get(key) not in (None, "", [])}


def _hard_constraints(constraints: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """不可裁剪的用户硬约束。"""

    keys = {
        "city",
        "people_count",
        "start_time",
        "duration_hours",
        "duration_is_hard",
        "budget",
        "budget_is_hard",
        "max_route_minutes",
        "route_limit_is_hard",
        "must_keywords",
        "must_pois",
        "excluded_keywords",
        "avoid_tags",
        "indoor_preferred",
    }
    result = {
        key: constraints.get(key) for key in keys if constraints.get(key) not in (None, "", [])
    }
    confirmed_actions = [
        action
        for action in state.get("booking_actions", []) or []
        if isinstance(action, dict) and action.get("status") in {"confirmed", "success"}
    ]
    if confirmed_actions:
        result["confirmed_actions"] = confirmed_actions
    return result


def _soft_preferences(constraints: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """可用于排序但不能覆盖本轮输入的软约束。"""

    return {
        "scenario": constraints.get("scenario"),
        "preferences": constraints.get("preferences", []),
        "preference_keywords": constraints.get("preference_keywords", []),
        "scene_requirements": constraints.get("scene_requirements", []),
        "memory_fit_tags": state.get("user_profile", {}).get("memory_fit_tags", []),
    }


def _negative_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    """本轮明确排斥内容。"""

    return {
        "excluded_keywords": constraints.get("excluded_keywords", []),
        "avoid_tags": constraints.get("avoid_tags", []),
        "must_not_pois": constraints.get("must_not_pois", []),
    }


def _top_k_pois_by_category(
    value: Dict[str, List[str]], top_k: int, field_name: str
) -> Tuple[dict[str, list[dict[str, Any]]], List[str]]:
    """按类别裁剪候选 POI，只保留 prompt 必需字段。"""

    clipped_fields = []
    result: dict[str, list[dict[str, Any]]] = {}
    for category, items in value.items():
        if len(items) > top_k:
            clipped_fields.append(f"{field_name}.{category}[{top_k}:{len(items)}]")
        sorted_items = sorted(
            items, key=lambda item: item.get("score", item.get("rating", 0)), reverse=True
        )
        result[str(category)] = [_compact_poi(item) for item in sorted_items[:top_k]]
    return result, clipped_fields


def _compact_poi(item: dict[str, Any]) -> dict[str, Any]:
    """保留 LLM 理解方案所需的 POI 最小字段。"""

    allowed = {
        "id",
        "name",
        "category",
        "subcategory",
        "lat",
        "lon",
        "address",
        "rating",
        "price_level",
        "tags",
        "score",
        "reason",
        "risk_flags",
    }
    return {key: item.get(key) for key in allowed if item.get(key) not in (None, "", [])}


def _tool_evidence(state: dict[str, Any], *, top_k: int) -> Tuple[list[dict[str, Any]], List[str]]:
    """读取状态中的工具证据摘要，不把完整结果放进 prompt。"""
    clipped_fields = []
    evidence = state.get("tool_evidence", []) or []
    if not isinstance(evidence, list):
        return [], []
    if not evidence and isinstance(state.get("candidate_pois"), dict):
        counts = _count_mapping(state.get("candidate_pois", {}))
        if counts:
            evidence = [{
                "tool_name": "poi_candidate_summary",
                "result_summary": {
                    "candidate_counts": counts,
                    "total": sum(counts.values()),
                },
                "source": "plan_state",
                "confidence": 0.5,
                "fallback_used": False,
            }]
    if len(evidence) > top_k:
        clipped_fields.append(f"tool_evidence[{top_k}:{len(evidence)}]")
    result: list[dict[str, Any]] = []
    for item in evidence[:top_k]:
        if not isinstance(item, dict):
            continue
        result.append({
            "tool_name": item.get("tool_name"),
            "result_summary": item.get("result_summary") or item.get("summary", {}),
            "source": item.get("source", ""),
            "fetched_at": item.get("fetched_at", ""),
            "expires_at": item.get("expires_at", ""),
            "confidence": item.get("confidence", 0.0),
            "fallback_used": bool(item.get("fallback_used")),
            "evidence_ref": item.get("evidence_ref") or _evidence_ref(item),
        })
    return result, clipped_fields


def _conversation_summary(state: dict[str, Any]) -> dict[str, Any]:
    """会话摘要只保留规划相关信息，不保留完整聊天历史。"""

    session_memory = (
        state.get("session_memory", {}) if isinstance(state.get("session_memory"), dict) else {}
    )
    return {
        "confirmed": session_memory.get("confirmed", []),
        "rejected_plans": session_memory.get("rejected_plans", []),
        "selected_plan_id": (
            session_memory.get("selected_plan_id")
            or (state.get("selected_plan") or {}).get("id", "")
        ),
        "recent_revisions": _safe_list(session_memory.get("recent_revisions"))[-5:],
        "pending_question": (
            state.get("clarify_question", "") if state.get("need_clarification") else ""
        ),
    }


def _public_issues(value: Any, *, limit: int) -> list[dict[str, Any]]:
    """压缩 issue，避免把 details 原样放入 prompt。"""

    issues = value if isinstance(value, list) else []
    return [
        {
            "code": item.get("code"),
            "severity": item.get("severity"),
            "message": item.get("message"),
            "suggestion": item.get("suggestion"),
            "target_plan_id": item.get("target_plan_id"),
            "target_item_id": item.get("target_item_id"),
        }
        for item in issues[:limit]
        if isinstance(item, dict)
    ]


def _infer_current_phase(state: dict[str, Any]) -> str:
    """根据 PlanState 字段推断当前规划阶段。"""

    if state.get("ranked_plans"):
        return "PLAN_VALIDATED"
    if state.get("verified_plans"):
        return "PLAN_VALIDATED"
    if state.get("candidate_plans"):
        return "PLAN_GENERATED"
    if state.get("recommended_pois"):
        return "CANDIDATES_RECALLED"
    if state.get("intent_type"):
        return "INTENT_PARSED"
    return "CREATED"


def _evidence_ref(item: dict[str, Any]) -> str:
    """生成稳定的工具证据引用 ID。"""

    raw = repr(sorted((str(key), str(value)) for key, value in item.items()))
    return "evidence_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
