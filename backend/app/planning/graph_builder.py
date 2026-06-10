from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.bus.event import Event, EventType
from app.bus.event_bus import publish_event_sync
from app.planning.nodes import GRAPH_NODES
from app.planning.nodes.intent_nodes import request_route
from app.planning.nodes.validation_nodes import failure_route, post_check_route
from app.planning.state import PlanningState


def build_planning_graph_v2():
    graph = StateGraph(PlanningState)
    for name, node in GRAPH_NODES.items():
        graph.add_node(name, _instrument_node(name, node))
    graph.add_edge(START, "request_context_loader")
    graph.add_edge("request_context_loader", "session_state_loader")
    graph.add_edge("session_state_loader", "memory_reader")
    graph.add_edge("memory_reader", "intent_resolver")
    graph.add_edge("intent_resolver", "session_preference_extractor")
    graph.add_edge("session_preference_extractor", "async_event_emitter")
    graph.add_edge("async_event_emitter", "request_router")
    graph.add_conditional_edges(
        "request_router",
        request_route,
        {
            "simple_qa": "simple_response_generator",
            "single_category_recommend": "constraint_builder",
            "full_itinerary_plan": "constraint_builder",
            "plan_adjustment": "constraint_builder",
        },
    )
    graph.add_edge("simple_response_generator", "session_state_saver")
    graph.add_conditional_edges(
        "constraint_builder",
        request_route,
        {
            "single_category_recommend": "recall_plan_compiler",
            "full_itinerary_plan": "recall_plan_compiler",
            "plan_adjustment": "plan_editor",
            "simple_qa": "simple_response_generator",
        },
    )
    graph.add_edge("plan_editor", "recall_plan_compiler")
    graph.add_edge("recall_plan_compiler", "collector")
    graph.add_edge("collector", "poi_scorer")
    graph.add_conditional_edges(
        "poi_scorer",
        request_route,
        {
            "single_category_recommend": "single_category_ranker",
            "full_itinerary_plan": "candidate_pool_balancer",
            "plan_adjustment": "candidate_pool_balancer",
            "simple_qa": "simple_response_generator",
        },
    )
    graph.add_edge("single_category_ranker", "response_assembler")
    graph.add_edge("candidate_pool_balancer", "route_planner")
    graph.add_edge("route_planner", "pre_ranker")
    graph.add_edge("pre_ranker", "availability_checker")
    graph.add_edge("availability_checker", "post_check_filter")
    graph.add_conditional_edges(
        "post_check_filter",
        post_check_route,
        {
            "final_ranker": "final_ranker",
            "failure_analyzer": "failure_analyzer",
        },
    )
    graph.add_conditional_edges(
        "failure_analyzer",
        failure_route,
        {
            "fallback_relaxation": "fallback_relaxation",
            "final_ranker": "final_ranker",
        },
    )
    graph.add_edge("fallback_relaxation", "recall_plan_compiler")
    graph.add_edge("final_ranker", "response_assembler")
    graph.add_edge("response_assembler", "response_generator")
    graph.add_edge("response_generator", "session_state_saver")
    graph.add_edge("session_state_saver", END)
    return graph.compile()


def _instrument_node(name: str, node):
    def wrapped(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
        state = value if isinstance(value, PlanningState) else PlanningState.model_validate(value)
        _publish_event(state, EventType.NODE_STARTED, node_name=name, status="running")
        if name == "response_generator":
            _publish_event(
                state, EventType.FINAL_RESPONSE_STARTED, node_name=name, status="running"
            )
        try:
            patch = node(value)
        except Exception as exc:
            _publish_event(
                state,
                EventType.NODE_FAILED,
                node_name=name,
                status="failed",
                payload={"error_summary": exc.__class__.__name__},
            )
            raise
        _publish_event(state, EventType.NODE_FINISHED, node_name=name, status="success")
        _publish_business_event(name, state, patch if isinstance(patch, dict) else {})
        return patch

    return wrapped


def _publish_event(
    state: PlanningState,
    event_type: EventType,
    *,
    node_name: str | None = None,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    publish_event_sync(
        Event(
            event_type=event_type,
            request_id=state.state_meta.request_id,
            run_id=state.state_meta.state_id,
            conversation_id=state.state_meta.session_id or None,
            user_id=state.state_meta.user_id or None,
            node_name=node_name,
            status=status,
            payload=payload or {},
        )
    )


def _publish_business_event(name: str, state: PlanningState, patch: dict[str, Any]) -> None:
    event_type, payload = _business_event_payload(name, state, patch)
    if not event_type:
        return
    _publish_event(state, event_type, node_name=name, status="success", payload=payload)


def _business_event_payload(
    name: str, state: PlanningState, patch: dict[str, Any]
) -> tuple[EventType | None, dict[str, Any]]:
    match name:
        case "intent_resolver":
            understanding = patch.get("llm_understanding") or state.llm_understanding
            if understanding:
                return (
                    EventType.INTENT_PARSED,
                    {
                        "request_type": understanding.intent.request_type,
                        "target_categories": list(
                            understanding.poi_recall_intent.target_logical_categories
                        ),
                        "slot_count": len(understanding.slots.required_slots),
                    },
                )
        case "constraint_builder":
            recall = patch.get("recall_plan") or state.recall_plan
            return (
                EventType.SLOTS_GENERATED,
                {"slot_count": len(recall.target_slots) if recall else 0},
            )
        case "recall_plan_compiler":
            compiled = patch.get("compiled_recall_plan") or state.compiled_recall_plan
            return (
                EventType.RECALL_PLAN_CREATED,
                {"query_count": len(compiled.queries) if compiled else 0},
            )
        case "collector":
            candidates = patch.get("candidates")
            stats = candidates.recall_stats if candidates else state.candidates.recall_stats
            return EventType.POI_RECALLED, {"total_count": stats.total_raw_count}
        case "poi_scorer":
            candidates = patch.get("candidates")
            scored = (
                candidates.scored_candidates if candidates else state.candidates.scored_candidates
            )
            return EventType.POI_SCORED, {
                "total_count": sum(len(items) for items in scored.values())
            }
        case "candidate_pool_balancer":
            candidates = patch.get("candidates")
            balanced = (
                candidates.balanced_candidates
                if candidates
                else state.candidates.balanced_candidates
            )
            return (
                EventType.POI_FILTERED,
                {"balanced_counts": {slot: len(items) for slot, items in balanced.items()}},
            )
        case "route_planner":
            plans = patch.get("plans")
            return (
                EventType.PLAN_GENERATED,
                {"plan_count": len(plans.candidate_plans) if plans else 0},
            )
        case "availability_checker":
            plans = patch.get("plans")
            return (
                EventType.PLAN_VALIDATED,
                {"available_plan_count": len(plans.candidate_plans) if plans else 0},
            )
        case "failure_analyzer":
            debug = patch.get("debug")
            reason = (debug.recall_debug if debug else state.debug.recall_debug).get(
                "failure_reason"
            )
            return EventType.PLAN_INSUFFICIENT, {"failure_reason": reason or "unknown"}
        case "fallback_relaxation":
            return (
                EventType.CONSTRAINT_RELAXED,
                {"failure_reason": state.debug.recall_debug.get("failure_reason") or "unknown"},
            )
        case "final_ranker":
            plans = patch.get("plans")
            return EventType.PLAN_RANKED, {"plan_count": len(plans.ranked_plans) if plans else 0}
        case "response_generator":
            return EventType.FINAL_RESPONSE_FINISHED, {}

    return None, {}


planning_graph_v2 = build_planning_graph_v2()
