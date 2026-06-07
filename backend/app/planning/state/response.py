from app.planning.state.base import *  # noqa: F403
from app.planning.state.context import *  # noqa: F403
from app.planning.state.understanding import *  # noqa: F403
from app.planning.state.constraints import *  # noqa: F403
from app.planning.state.recall import *  # noqa: F403
from app.planning.state.plans import *  # noqa: F403


class ResponseState(StateModel):
    response_type: str = "simple_text"
    response_payload: dict[str, Any] | None = None
    final_text: str | None = None


class NodeTrace(StateModel):
    node: str
    status: str
    latency_ms: int | None = None
    message: str | None = None


class LLMCallTrace(StateModel):
    call_id: str
    purpose: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class DebugState(StateModel):
    node_trace: list[NodeTrace] = Field(default_factory=list)
    llm_calls: list[LLMCallTrace] = Field(default_factory=list)
    recall_debug: dict[str, Any] = Field(default_factory=dict)
    constraint_debug: dict[str, Any] = Field(default_factory=dict)
    risk_debug: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class AsyncEventInfo(StateModel):
    enabled: bool = False
    event_id: str | None = None
    payload_summary: str | None = None


class FeedbackWaitingInfo(StateModel):
    enabled: bool = False
    expected_feedback_actions: list[str] = Field(default_factory=list)


class AsyncEventState(StateModel):
    memory_extraction_event: AsyncEventInfo = Field(default_factory=AsyncEventInfo)
    planning_trace_event: AsyncEventInfo = Field(default_factory=AsyncEventInfo)
    feedback_waiting: FeedbackWaitingInfo = Field(default_factory=FeedbackWaitingInfo)


class PlanningState(StateModel):
    state_meta: StateMeta = Field(default_factory=StateMeta)
    user_info: UserInfo = Field(default_factory=UserInfo)
    context: ContextState = Field(default_factory=ContextState)
    llm_understanding: LLMUnderstanding | None = None
    constraints: FinalConstraints | None = None
    recall_plan: LogicalRecallPlan | None = None
    compiled_recall_plan: CompiledRecallPlan | None = None
    candidates: CandidateState = Field(default_factory=CandidateState)
    plans: PlanResultsState = Field(default_factory=PlanResultsState)
    response: ResponseState = Field(default_factory=ResponseState)
    debug: DebugState = Field(default_factory=DebugState)
    async_events: AsyncEventState = Field(default_factory=AsyncEventState)


def create_planning_state(
    user_message: str,
    *,
    session_id: str = "",
    user_id: str = "",
    city: str | None = None,
    message_id: str = "",
    timezone: str = "Asia/Shanghai",
    source: str = "api",
    geo_location: dict[str, Any] | None = None,
    manual_origin: dict[str, Any] | None = None,
) -> PlanningState:
    geo = GeoLocation.model_validate(geo_location) if geo_location else None
    origin = OriginPoint.model_validate(manual_origin) if manual_origin else None
    if origin is None and geo is not None:
        origin = OriginPoint(name="当前位置", lat=geo.lat, lng=geo.lng, source=geo.source)
    effective_user = user_id or session_id
    return PlanningState(
        state_meta=StateMeta(
            session_id=session_id,
            user_id=effective_user,
            message_id=message_id or f"msg_{uuid4().hex}",
            timezone=timezone,
            source=source,
        ),
        user_info=UserInfo(
            user_id=effective_user, city=city, geo_location=geo, default_origin=origin
        ),
        context=ContextState(
            conversation_context=ConversationContext(last_user_message=user_message)
        ),
    )


def planning_state_from_legacy(state: dict[str, Any]) -> PlanningState:
    query = str(state.get("user_query") or "")
    profile = state.get("user_profile") if isinstance(state.get("user_profile"), dict) else {}
    result = create_planning_state(
        query,
        session_id=str(state.get("session_id") or ""),
        user_id=str(profile.get("user_id") or state.get("session_id") or ""),
    )
    result.response.final_text = str(state.get("response_text") or "") or None
    result.context.current_plan_state = CurrentPlanContext(
        has_active_plan=bool(state.get("ranked_plans")),
        last_request_type=str(state.get("intent_type") or "") or None,
        last_constraints_snapshot=state.get("constraints") or None,
        last_ranked_plans=list(state.get("ranked_plans") or []),
        selected_or_referenced_plan_id=str((state.get("selected_plan") or {}).get("id") or "")
        or None,
    )
    return result


def planning_state_to_legacy(state: PlanningState) -> dict[str, Any]:
    request_type = state.llm_understanding.intent.request_type if state.llm_understanding else ""
    intent_type = {
        "simple_qa": "simple_qa",
        "single_category_recommend": "category_recommend",
        "full_itinerary_plan": "full_trip_plan",
        "plan_adjustment": "full_trip_plan",
    }.get(request_type, "full_trip_plan")
    payload = state.response.response_payload or {}
    safe_debug = {
        "node_trace": [trace.model_dump(mode="json") for trace in state.debug.node_trace],
        "llm_calls": [trace.model_dump(mode="json") for trace in state.debug.llm_calls],
        "constraint_debug": state.debug.constraint_debug,
        "risk_debug": state.debug.risk_debug,
        "errors": state.debug.errors,
    }
    constraints = _public_constraints(state)
    target_categories = (
        list(state.llm_understanding.poi_recall_intent.target_logical_categories)
        if state.llm_understanding
        else []
    )
    response_issues = [
        issue
        for plan in payload.get("plans", [])
        if isinstance(plan, dict)
        for issue in plan.get("issues", [])
        if isinstance(issue, dict)
    ]
    return {
        "response_text": state.response.final_text or "",
        "execution_status": (
            "simulated" if payload.get("selected_plan") or payload.get("plans") else "pending"
        ),
        "intent_type": intent_type,
        "answer_mode": "simple_qa" if request_type == "simple_qa" else "trip_plan",
        "need_clarification": False,
        "missing_constraints": [],
        "clarify_question": "",
        "selected_plan": payload.get("selected_plan", {}),
        "ranked_plans": payload.get("plans", []),
        "errors": [*state.debug.errors, *response_issues],
        "logs": [
            trace.message or f"{trace.node}: {trace.status}" for trace in state.debug.node_trace
        ],
        "session_id": state.state_meta.session_id,
        "trace_id": state.state_meta.request_id,
        "run_id": state.state_meta.state_id,
        "revision_id": "",
        "is_revision": request_type == "plan_adjustment",
        "task_id": "",
        "final_text": state.response.final_text or "",
        "response_payload": payload,
        "plan_state_id": state.state_meta.state_id,
        "constraints": constraints,
        "target_categories": target_categories,
        "weather": {},
        "routes": [],
        "debug": safe_debug,
    }


def _public_constraints(state: PlanningState) -> dict[str, Any]:
    if state.constraints is None:
        return {}
    constraints = state.constraints
    understanding = state.llm_understanding
    return {
        "city": constraints.hard_constraints.city,
        "origin_name": (
            constraints.hard_constraints.origin.name
            if constraints.hard_constraints.origin
            else None
        ),
        "required_slots": list(constraints.hard_constraints.required_slots),
        "slot_duration_minutes": dict(constraints.hard_constraints.slot_duration_minutes),
        "slot_logical_categories": dict(constraints.hard_constraints.slot_logical_categories),
        "slot_names": dict(constraints.hard_constraints.slot_names),
        "avoid_keywords": list(constraints.hard_constraints.avoid_keywords),
        "duration_minutes": constraints.time_policy.duration_minutes,
        "duration_hours": (
            round(constraints.time_policy.duration_minutes / 60, 2)
            if constraints.time_policy.duration_minutes
            else None
        ),
        "start_time": (
            constraints.time_policy.start_time.strftime("%H:%M")
            if constraints.time_policy.start_time
            else None
        ),
        "budget": constraints.budget_policy.total_budget,
        "budget_per_person": constraints.budget_policy.budget_per_person,
        "people_count": understanding.scene.people_count if understanding else None,
        "scenario": understanding.scene.scene_type if understanding else None,
        "max_route_minutes": constraints.hard_constraints.max_route_minutes,
        "initial_radius_km": constraints.distance_policy.initial_radius_km,
        "max_radius_km": constraints.distance_policy.max_radius_km,
        "preferred_categories": list(constraints.soft_preferences.preferred_categories),
        "preference_keywords": list(constraints.soft_preferences.preference_keywords),
    }
