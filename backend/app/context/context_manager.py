from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.agents.session_summary_agent import compress_session_summary
from app.planning.state import (
    ContextState,
    ConversationTurn,
    CurrentPlanContext,
    PreferenceCluster,
    SessionSummary,
)

SESSION_SUMMARY_RECENT_TURN_THRESHOLD = 8
PROMPT_CONTEXT_TOKEN_BUDGET = 6000


class ContextManager:
    """Assembles request context without making planning decisions."""

    def apply_session_payload(
        self, context: ContextState, saved: dict[str, Any] | None
    ) -> ContextState:
        if not saved:
            context.prompt_context_pack = self.build_prompt_context_pack(context)
            return context

        result = context.model_copy(deep=True)
        latest = saved.get("latest_planning_state") or saved.get("latest_state") or {}
        response = saved.get("latest_planning_response") or saved.get("latest_response") or {}
        ranked = response.get("ranked_plans") or latest.get("ranked_plans") or []
        last_intent = str(latest.get("intent_type") or response.get("intent_type") or "")

        result.current_plan_state = CurrentPlanContext(
            has_active_plan=bool(
                ranked
                or response.get("response_payload")
                or last_intent in {"full_trip_plan", "category_recommend", "poi_search"}
            ),
            last_request_type=last_intent or None,
            last_constraints_snapshot=latest.get("constraints") or None,
            last_ranked_plans=list(ranked or [])[:3],
            selected_or_referenced_plan_id=str(
                (response.get("selected_plan") or {}).get("id") or ""
            )
            or None,
        )
        result.conversation_context.recent_turns = self.recent_turns(saved)
        result.conversation_context.session_summary = self.session_summary(saved)
        result.conversation_context.history_summary = (
            result.conversation_context.session_summary.summary or None
        )
        result.prompt_context_pack = self.build_prompt_context_pack(result)
        return result

    def recent_turns(self, saved: dict[str, Any]) -> list[ConversationTurn]:
        turns = saved.get("turns") or []
        if not isinstance(turns, list):
            return []
        limit = max(1, min(int(settings.max_recent_turns or 5), 5))
        return [
            ConversationTurn(role="user", content=str(turn.get("user_query") or ""))
            for turn in turns[-limit:]
            if isinstance(turn, dict) and turn.get("user_query")
        ]

    def session_summary(self, saved: dict[str, Any]) -> SessionSummary:
        existing = saved.get("session_summary")
        if isinstance(existing, dict) and not self.should_update_session_summary(saved):
            try:
                return SessionSummary.model_validate(existing)
            except Exception:
                pass
        return self.update_session_summary(saved)

    def update_session_summary(self, saved: dict[str, Any]) -> SessionSummary:
        fallback = self.build_session_summary(saved)
        llm_payload = _summary_llm_payload(saved, fallback)
        compressed = compress_session_summary(llm_payload)
        if isinstance(compressed, dict):
            try:
                llm_summary = SessionSummary.model_validate(compressed)
                return _merge_summary_safely(fallback, llm_summary)
            except Exception:
                pass
        return fallback

    def should_update_session_summary(
        self, saved: dict[str, Any], *, is_revision: bool | None = None
    ) -> bool:
        turns = saved.get("turns") if isinstance(saved.get("turns"), list) else []
        if len(turns) > SESSION_SUMMARY_RECENT_TURN_THRESHOLD:
            return True
        if is_revision is True:
            return True
        latest = (
            saved.get("latest_planning_state")
            if isinstance(saved.get("latest_planning_state"), dict)
            else {}
        )
        response = (
            saved.get("latest_planning_response")
            if isinstance(saved.get("latest_planning_response"), dict)
            else {}
        )
        if _plans_from_response(response, latest):
            return True
        return not isinstance(saved.get("session_summary"), dict)

    def build_session_summary(self, saved: dict[str, Any]) -> SessionSummary:
        latest = saved.get("latest_planning_state") or saved.get("latest_state") or {}
        response = saved.get("latest_planning_response") or saved.get("latest_response") or {}
        constraints = (
            latest.get("constraints") if isinstance(latest.get("constraints"), dict) else {}
        )
        plans = _plans_from_response(response, latest)
        active_constraints = _active_constraints(constraints)
        negative_constraints = _negative_constraints(constraints)
        open_questions = _open_questions(response, latest)
        current_focus = _current_focus(saved, constraints, bool(plans))
        summary = _summary_text(active_constraints, negative_constraints, current_focus, plans)
        return SessionSummary(
            summary=summary,
            active_constraints=active_constraints,
            negative_constraints=negative_constraints,
            resolved_references=_resolved_references(response, plans),
            current_focus=current_focus,
            last_plan_ids=_plan_ids(plans),
            open_questions=open_questions,
        )

    def build_prompt_context_pack(self, context: ContextState) -> dict[str, Any]:
        summary = context.conversation_context.session_summary
        pack = {
            "session_summary": summary.model_dump(mode="json"),
            "recent_turns": [
                turn.model_dump(mode="json") for turn in context.conversation_context.recent_turns
            ],
            "last_plan_snapshot": {
                "has_active_plan": context.current_plan_state.has_active_plan,
                "last_request_type": context.current_plan_state.last_request_type,
                "selected_or_referenced_plan_id": (
                    context.current_plan_state.selected_or_referenced_plan_id
                ),
                "last_plan_ids": [
                    str(plan.get("id") or plan.get("plan_id") or "")
                    for plan in context.current_plan_state.last_ranked_plans[:3]
                    if isinstance(plan, dict)
                ],
            },
            "memory_context": {
                "positive_tags": [
                    tag.model_dump(mode="json")
                    for tag in context.user_preference_profile.positive_tags[:12]
                ],
                "negative_tags": [
                    tag.model_dump(mode="json")
                    for tag in context.user_preference_profile.negative_tags[:12]
                ],
                "similar_profiles": [
                    _cluster_payload(cluster)
                    for cluster in context.user_preference_profile.positive_clusters[:3]
                ],
            },
        }
        return self.trim_prompt_context_pack(pack)

    def trim_prompt_context_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        if estimate_prompt_tokens(pack) <= PROMPT_CONTEXT_TOKEN_BUDGET:
            return pack
        trimmed = json.loads(json.dumps(pack, ensure_ascii=False, default=str))
        if len(trimmed.get("recent_turns", [])) > 3:
            trimmed["recent_turns"] = trimmed["recent_turns"][-3:]
        memory = (
            trimmed.get("memory_context") if isinstance(trimmed.get("memory_context"), dict) else {}
        )
        memory["positive_tags"] = list(memory.get("positive_tags", []))[:6]
        memory["negative_tags"] = list(memory.get("negative_tags", []))[:6]
        memory["similar_profiles"] = list(memory.get("similar_profiles", []))[:2]
        last_plan = (
            trimmed.get("last_plan_snapshot")
            if isinstance(trimmed.get("last_plan_snapshot"), dict)
            else {}
        )
        last_plan["last_plan_ids"] = list(last_plan.get("last_plan_ids", []))[:3]
        trimmed["prompt_context_meta"] = {
            "trimmed": True,
            "estimated_tokens_before": estimate_prompt_tokens(pack),
            "estimated_tokens_after": estimate_prompt_tokens(trimmed),
            "budget": PROMPT_CONTEXT_TOKEN_BUDGET,
        }
        return trimmed


def _plans_from_response(response: dict[str, Any], latest: dict[str, Any]) -> list[dict[str, Any]]:
    payload = (
        response.get("response_payload")
        if isinstance(response.get("response_payload"), dict)
        else {}
    )
    plans = payload.get("plans") or response.get("ranked_plans") or latest.get("ranked_plans") or []
    return [plan for plan in plans if isinstance(plan, dict)]


def estimate_prompt_tokens(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return max(1, len(text) // 3)


def _summary_llm_payload(saved: dict[str, Any], fallback: SessionSummary) -> dict[str, Any]:
    latest = (
        saved.get("latest_planning_state")
        if isinstance(saved.get("latest_planning_state"), dict)
        else {}
    )
    response = (
        saved.get("latest_planning_response")
        if isinstance(saved.get("latest_planning_response"), dict)
        else {}
    )
    turns = saved.get("turns") if isinstance(saved.get("turns"), list) else []
    return {
        "previous_summary": (
            saved.get("session_summary") if isinstance(saved.get("session_summary"), dict) else {}
        ),
        "rule_summary": fallback.model_dump(mode="json"),
        "recent_turns": [
            {
                "user_query": turn.get("user_query"),
                "response_text": turn.get("response_text"),
                "is_revision": turn.get("is_revision"),
            }
            for turn in turns[-12:]
            if isinstance(turn, dict)
        ],
        "latest_constraints": latest.get("constraints", {}),
        "latest_response": {
            "intent_type": response.get("intent_type"),
            "selected_plan": response.get("selected_plan"),
            "ranked_plan_count": len(response.get("ranked_plans", []) or []),
        },
    }


def _merge_summary_safely(fallback: SessionSummary, llm_summary: SessionSummary) -> SessionSummary:
    active_constraints = {
        **fallback.active_constraints,
        **{
            key: value
            for key, value in llm_summary.active_constraints.items()
            if value not in (None, "", [])
        },
    }
    negative_constraints = _dedupe([
        *fallback.negative_constraints,
        *llm_summary.negative_constraints,
    ])[:20]
    last_plan_ids = _dedupe([*fallback.last_plan_ids, *llm_summary.last_plan_ids])[:5]
    return SessionSummary(
        summary=llm_summary.summary or fallback.summary,
        active_constraints=active_constraints,
        negative_constraints=negative_constraints,
        resolved_references={**fallback.resolved_references, **llm_summary.resolved_references},
        current_focus=llm_summary.current_focus or fallback.current_focus,
        last_plan_ids=last_plan_ids,
        open_questions=_dedupe([*fallback.open_questions, *llm_summary.open_questions])[:8],
    )


def _plan_ids(plans: list[dict[str, Any]]) -> list[str]:
    return [
        plan_id
        for plan in plans[:3]
        if (plan_id := str(plan.get("id") or plan.get("plan_id") or "").strip())
    ]


def _active_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "scenario",
        "city",
        "origin_name",
        "people_count",
        "distance_preference",
        "duration_minutes",
        "duration_hours",
        "start_time",
        "budget",
        "budget_per_person",
        "max_route_minutes",
        "required_slots",
        "preferred_categories",
        "preference_keywords",
    }
    return {
        key: value
        for key, value in constraints.items()
        if key in allowed and value not in (None, "", [])
    }


def _negative_constraints(constraints: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("avoid_keywords", "excluded_keywords", "negative_constraints"):
        raw = constraints.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
    return _dedupe(values)[:20]


def _open_questions(response: dict[str, Any], latest: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    for payload in (response, latest):
        if payload.get("need_clarification") and payload.get("clarify_question"):
            questions.append(str(payload["clarify_question"]))
    return _dedupe(questions)[:5]


def _current_focus(saved: dict[str, Any], constraints: dict[str, Any], has_plans: bool) -> str:
    turns = saved.get("turns") if isinstance(saved.get("turns"), list) else []
    latest_turn = turns[-1] if turns and isinstance(turns[-1], dict) else {}
    query = str(latest_turn.get("user_query") or saved.get("latest_planning_query") or "")
    if any(token in query for token in ("换", "替换", "改成")) and any(
        token in query for token in ("餐厅", "吃饭", "美食")
    ):
        return "replace_restaurant"
    if any(token in query for token in ("预算", "便宜", "贵")):
        return "adjust_budget"
    if any(token in query for token in ("远", "近", "路线", "少走")):
        return "adjust_route"
    if constraints:
        return "continue_planning"
    return "refine_plan" if has_plans else "new_planning"


def _resolved_references(response: dict[str, Any], plans: list[dict[str, Any]]) -> dict[str, Any]:
    selected = (
        response.get("selected_plan") if isinstance(response.get("selected_plan"), dict) else {}
    )
    return {
        "selected_plan_id": (
            selected.get("id") or selected.get("plan_id") or (_plan_ids(plans)[0] if plans else "")
        ),
        "plan_count": len(plans),
    }


def _summary_text(
    active_constraints: dict[str, Any],
    negative_constraints: list[str],
    current_focus: str,
    plans: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    if scene := active_constraints.get("scenario"):
        parts.append(f"scene={scene}")
    if budget := active_constraints.get("budget"):
        parts.append(f"budget={budget}")
    if duration := active_constraints.get("duration_minutes") or active_constraints.get(
        "duration_hours"
    ):
        parts.append(f"duration={duration}")
    if categories := active_constraints.get("preferred_categories"):
        parts.append("categories=" + ",".join(str(item) for item in categories[:4]))
    if negative_constraints:
        parts.append("avoid=" + ",".join(negative_constraints[:4]))
    if current_focus:
        parts.append(f"focus={current_focus}")
    if plans:
        parts.append(f"last_plans={len(plans)}")
    return "；".join(parts)


def _cluster_payload(cluster: PreferenceCluster) -> dict[str, Any]:
    return {
        "cluster_id": cluster.cluster_id,
        "core_tags": cluster.core_tags[:8],
        "similarity_score": cluster.similarity_score,
    }


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result
