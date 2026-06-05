from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

RequestType = Literal[
    "simple_qa", "single_category_recommend", "full_itinerary_plan", "plan_adjustment"
]
LogicalCategory = Literal[
    "restaurant", "activity", "attraction", "shopping", "entertainment", "fitness", "beauty"
]

PHYSICAL_TABLES: dict[str, str] = {
    "restaurant": "poi_restaurant",
    "activity": "poi_activities",
    "attraction": "poi_attractions",
    "shopping": "poi_shoppings",
    "entertainment": "poi_entertainment",
    "fitness": "poi_fitness",
    "beauty": "poi_beauty",
}
LEGACY_CATEGORIES = {category: f"poi_{category}" for category in PHYSICAL_TABLES}


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeoLocation(StateModel):
    lat: float = Field(description="纬度")
    lng: float = Field(description="经度")
    accuracy_meters: float | None = Field(default=None, description="定位精度")
    source: str = Field(default="manual_input", description="定位来源")
    updated_at: datetime | None = Field(default=None, description="更新时间")


class OriginPoint(StateModel):
    name: str = Field(default="当前位置", description="出发点名称")
    lat: float = Field(description="纬度")
    lng: float = Field(description="经度")
    address: str | None = Field(default=None, description="地址")
    source: str | None = Field(default=None, description="来源")


class StateMeta(StateModel):
    state_id: str = Field(default_factory=lambda: f"state_{uuid4().hex}", description="状态 ID")
    request_id: str = Field(default_factory=lambda: f"req_{uuid4().hex}", description="请求 ID")
    message_id: str = Field(default_factory=lambda: f"msg_{uuid4().hex}", description="消息 ID")
    session_id: str = Field(default="", description="会话 ID")
    user_id: str = Field(default="", description="用户 ID")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    timezone: str = Field(default="Asia/Shanghai", description="用户时区")
    state_version: str = Field(default="2.0", description="Schema 版本")
    source: str = Field(default="api", description="请求来源")


class UserInfo(StateModel):
    user_id: str = ""
    nickname: str | None = None
    city: str | None = None
    district: str | None = None
    geo_location: GeoLocation | None = None
    default_origin: OriginPoint | None = None


class ConversationTurn(StateModel):
    role: str
    content: str
    created_at: datetime | None = None


class ConversationContext(StateModel):
    history_summary: str | None = None
    recent_turns: list[ConversationTurn] = Field(default_factory=list)
    last_user_message: str = ""


class CurrentPlanContext(StateModel):
    has_active_plan: bool = False
    last_request_type: str | None = None
    last_constraints_snapshot: dict[str, Any] | None = None
    last_ranked_plans: list[dict[str, Any]] = Field(default_factory=list)
    selected_or_referenced_plan_id: str | None = None
    frozen_slots: list[str] = Field(default_factory=list)
    target_edit_slots: list[str] = Field(default_factory=list)


class PreferenceTag(StateModel):
    tag_id: str
    tag_name: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_count: int = Field(default=1, ge=0)
    source: str = "memory"
    updated_at: datetime | None = None


class PreferenceCluster(StateModel):
    cluster_id: str
    cluster_name: str
    core_tags: list[str] = Field(default_factory=list)
    similarity_score: float = Field(default=0, ge=0, le=1)
    direction: Literal["positive", "negative"] = "positive"


class UserRankerProfile(StateModel):
    distance_weight_delta: float = 0
    budget_weight_delta: float = 0
    crowd_weight_delta: float = 0
    rating_weight_delta: float = 0
    scene_weight_delta: float = 0
    memory_weight_delta: float = 0
    category_affinity: dict[str, float] = Field(default_factory=dict)


class UserPreferenceProfile(StateModel):
    positive_tags: list[PreferenceTag] = Field(default_factory=list)
    negative_tags: list[PreferenceTag] = Field(default_factory=list)
    positive_clusters: list[PreferenceCluster] = Field(default_factory=list)
    negative_clusters: list[PreferenceCluster] = Field(default_factory=list)
    ranker_profile: UserRankerProfile = Field(default_factory=UserRankerProfile)


class SessionPreferenceProfile(StateModel):
    scene_type: str = "unknown"
    companion_structure: str = "unknown"
    person_tags: list[str] = Field(default_factory=list)
    activity_preferences: list[str] = Field(default_factory=list)
    dining_preferences: list[str] = Field(default_factory=list)
    route_preferences: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: list[str] = Field(default_factory=list)
    negative_preferences: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source: str = "sync_session"


class POITableTagInfo(StateModel):
    physical_table: str
    logical_category: str
    category_name: str
    physical_fields: list[str] = Field(default_factory=list)
    filter_fields: list[str] = Field(default_factory=list)
    tag_fields: list[str] = Field(default_factory=list)
    supported_logic_tags: list[str] = Field(default_factory=list)
    total_logic_tag_count: int = 0
    queryable_fields: list[str] = Field(default_factory=list)
    default_sort: list[str] = Field(default_factory=list)
    es_search_fields: list[str] = Field(default_factory=list)


def default_tag_tables() -> dict[str, POITableTagInfo]:
    fields = ["poi_id", "name", "subcategory", "logic_tags", "address", "lat", "lng", "rating", "avg_price"]
    return {
        category: POITableTagInfo(
            physical_table=table,
            logical_category=category,
            category_name=category,
            physical_fields=[],
            filter_fields=[],
            tag_fields=[],
            queryable_fields=fields,
            default_sort=["rating DESC"],
            es_search_fields=["name", "logic_tags"],
        )
        for category, table in PHYSICAL_TABLES.items()
    }


class POILogicalTagCatalog(StateModel):
    tag_version: str = "1.0"
    tables: dict[str, POITableTagInfo] = Field(default_factory=default_tag_tables)


class ContextState(StateModel):
    conversation_context: ConversationContext = Field(default_factory=ConversationContext)
    current_plan_state: CurrentPlanContext = Field(default_factory=CurrentPlanContext)
    user_preference_profile: UserPreferenceProfile = Field(default_factory=UserPreferenceProfile)
    session_preference_profile: SessionPreferenceProfile = Field(default_factory=SessionPreferenceProfile)
    poi_logical_tag_catalog: POILogicalTagCatalog = Field(default_factory=POILogicalTagCatalog)


class IntentResult(StateModel):
    request_type: RequestType = "full_itinerary_plan"
    is_followup: bool = False
    adjustment_type: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)


class SceneUnderstanding(StateModel):
    scene_type: str = "unknown"
    party_type: str = "unknown"
    people_count: int | None = Field(default=None, ge=1)
    has_child: bool = False
    child_age: int | None = Field(default=None, ge=0)


class SlotDetail(StateModel):
    slot_id: str
    slot_name: str
    required: bool = True
    expected_duration_minutes: int | None = Field(default=None, ge=0)
    candidate_logical_categories: list[str] = Field(default_factory=list)


class SlotUnderstanding(StateModel):
    required_slots: list[str] = Field(default_factory=list)
    optional_slots: list[str] = Field(default_factory=list)
    slot_details: list[SlotDetail] = Field(default_factory=list)


class CategoryTagRequirement(StateModel):
    logical_category: str
    target_slot: str
    positive_logic_tags: list[str] = Field(default_factory=list)
    negative_logic_tags: list[str] = Field(default_factory=list)


class POIRecallIntent(StateModel):
    target_logical_categories: list[str] = Field(default_factory=list)
    category_tag_requirements: list[CategoryTagRequirement] = Field(default_factory=list)


class POIKeywordIntent(StateModel):
    must_poi_keywords: list[str] = Field(default_factory=list)
    avoid_poi_keywords: list[str] = Field(default_factory=list)
    preference_poi_keywords: list[str] = Field(default_factory=list)
    keyword_search_engine: str = "mysql_like"


class MessagePreferenceTags(StateModel):
    liked_tags: list[PreferenceTag] = Field(default_factory=list)
    disliked_tags: list[PreferenceTag] = Field(default_factory=list)


class BudgetUnderstanding(StateModel):
    budget_per_person: float | None = Field(default=None, ge=0)
    total_budget: float | None = Field(default=None, ge=0)
    budget_preference: str = "unknown"
    budget_is_explicit: bool = False


class DistanceUnderstanding(StateModel):
    distance_preference: str = "unknown"
    origin_text: str | None = None
    origin_source: str | None = None


class TimeUnderstanding(StateModel):
    start_time: datetime | None = None
    return_home_time: datetime | None = None
    duration_hours: float | None = Field(default=None, ge=0)
    time_is_explicit: bool = False


class RatingUnderstanding(StateModel):
    min_rating: float | None = Field(default=None, ge=0, le=5)
    rating_preference: str = "unknown"


class DefaultsUsed(StateModel):
    used_default_origin: bool = False
    used_default_budget: bool = False
    used_default_duration: bool = False
    used_default_start_time: bool = False
    used_default_return_time: bool = False


class LLMUnderstanding(StateModel):
    raw_user_message: str = ""
    intent: IntentResult = Field(default_factory=IntentResult)
    scene: SceneUnderstanding = Field(default_factory=SceneUnderstanding)
    slots: SlotUnderstanding = Field(default_factory=SlotUnderstanding)
    poi_recall_intent: POIRecallIntent = Field(default_factory=POIRecallIntent)
    poi_keyword_intent: POIKeywordIntent = Field(default_factory=POIKeywordIntent)
    preference_tags_from_message: MessagePreferenceTags = Field(default_factory=MessagePreferenceTags)
    budget: BudgetUnderstanding = Field(default_factory=BudgetUnderstanding)
    distance: DistanceUnderstanding = Field(default_factory=DistanceUnderstanding)
    time: TimeUnderstanding = Field(default_factory=TimeUnderstanding)
    rating: RatingUnderstanding = Field(default_factory=RatingUnderstanding)
    defaults_used: DefaultsUsed = Field(default_factory=DefaultsUsed)


class HardConstraints(StateModel):
    city: str | None = None
    origin: OriginPoint | None = None
    avoid_keywords: list[str] = Field(default_factory=list)
    required_slots: list[str] = Field(default_factory=list)
    max_total_duration_minutes: int | None = None
    max_route_minutes: int | None = None
    must_include_poi_ids: list[str] = Field(default_factory=list)
    excluded_poi_ids: list[str] = Field(default_factory=list)


class SoftPreferences(StateModel):
    liked_logic_tags: list[str] = Field(default_factory=list)
    disliked_logic_tags: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    disliked_categories: list[str] = Field(default_factory=list)
    preference_keywords: list[str] = Field(default_factory=list)


class DistancePolicy(StateModel):
    initial_radius_km: float = 5
    fallback_radius_km: float = 8
    max_radius_km: float = 12
    max_pair_distance_km: float = 8
    distance_score_policy: dict[str, float] = Field(default_factory=dict)


class BudgetPolicy(StateModel):
    budget_per_person: float | None = None
    soft_upper_per_person: float | None = None
    hard_upper_per_person: float | None = None
    total_budget: float | None = None
    allow_unknown_price: bool = True


class TimePolicy(StateModel):
    start_time: datetime | None = None
    return_home_time: datetime | None = None
    duration_minutes: int | None = None
    meal_time_window: dict[str, list[str]] = Field(default_factory=dict)


class RatingPolicy(StateModel):
    min_rating_initial: float = 4.0
    min_rating_fallback: float = 3.8
    min_rating_floor: float = 3.8


class FallbackLevel(StateModel):
    level: int
    radius_km: float
    min_rating: float | None = None
    price_multiplier: float | None = None
    subcategory_filter_mode: Literal["hard", "soft"] = "soft"
    allow_unknown_price: bool = True


class FallbackPolicy(StateModel):
    levels: list[FallbackLevel] = Field(default_factory=list)


class FinalConstraints(StateModel):
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    soft_preferences: SoftPreferences = Field(default_factory=SoftPreferences)
    distance_policy: DistancePolicy = Field(default_factory=DistancePolicy)
    budget_policy: BudgetPolicy = Field(default_factory=BudgetPolicy)
    time_policy: TimePolicy = Field(default_factory=TimePolicy)
    rating_policy: RatingPolicy = Field(default_factory=RatingPolicy)
    fallback_policy: FallbackPolicy = Field(default_factory=FallbackPolicy)
    merge_policy_applied: dict[str, str] = Field(default_factory=dict)


class SlotRecallRequirement(StateModel):
    slot_id: str
    logical_categories: list[str] = Field(default_factory=list)
    positive_logic_tags: list[str] = Field(default_factory=list)
    negative_logic_tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=400, ge=1, le=500)


class KeywordRecallPlan(StateModel):
    must_keywords: list[str] = Field(default_factory=list)
    preference_keywords: list[str] = Field(default_factory=list)
    avoid_keywords: list[str] = Field(default_factory=list)


class LogicalRecallPlan(StateModel):
    target_slots: list[str] = Field(default_factory=list)
    slot_recall_requirements: list[SlotRecallRequirement] = Field(default_factory=list)
    keyword_recall: KeywordRecallPlan = Field(default_factory=KeywordRecallPlan)


class ESNameMatchPlan(StateModel):
    enabled: bool = False
    should_keywords: list[str] = Field(default_factory=list)
    must_keywords: list[str] = Field(default_factory=list)
    avoid_keywords: list[str] = Field(default_factory=list)


class CompiledRecallQuery(StateModel):
    query_id: str
    slot_id: str
    logical_category: str
    physical_table: str
    safe_return_fields: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    es_name_match: ESNameMatchPlan = Field(default_factory=ESNameMatchPlan)
    sort: list[str] = Field(default_factory=list)
    limit: int = Field(default=400, ge=1, le=500)
    fallback_enabled: bool = True

    @field_validator("physical_table")
    @classmethod
    def validate_physical_table(cls, value: str) -> str:
        if value not in set(PHYSICAL_TABLES.values()):
            raise ValueError("physical_table must come from the system whitelist")
        return value

    @field_validator("safe_return_fields")
    @classmethod
    def validate_safe_return_fields(cls, value: list[str]) -> list[str]:
        if "*" in value or any("SELECT " in field.upper() for field in value):
            raise ValueError("safe_return_fields cannot contain SQL or wildcard fields")
        return value


class MustPOIResolutionPlan(StateModel):
    enabled: bool = False
    keywords: list[str] = Field(default_factory=list)
    bypass_normal_filters: bool = True
    mark_must_include: bool = True
    if_far_then_warning: bool = True


class CompiledRecallPlan(StateModel):
    queries: list[CompiledRecallQuery] = Field(default_factory=list)
    must_poi_resolution: MustPOIResolutionPlan = Field(default_factory=MustPOIResolutionPlan)


class QueryRecallStat(StateModel):
    query_id: str
    raw_count: int = 0
    after_hard_filter_count: int = 0
    fallback_level: int = 0
    error: str | None = None


class RecallStats(StateModel):
    by_query: list[QueryRecallStat] = Field(default_factory=list)
    total_raw_count: int = 0
    total_after_filter_count: int = 0
    fallback_used: bool = False


class SafePOICandidate(StateModel):
    poi_id: str
    name: str
    logical_category: str
    physical_table: str
    subcategory: str | None = None
    logic_tags: list[str] = Field(default_factory=list)
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    distance_km: float | None = None
    rating: float | None = None
    avg_price: float | None = None
    image_url: str | None = None
    images: list[str] = Field(default_factory=list)
    recall_source: str = "dynamic_sql"
    fallback_level: int = 0
    must_include: bool = False
    raw_extra: dict[str, Any] = Field(default_factory=dict)


class POIScoreBreakdown(StateModel):
    quality_score: float = 0
    distance_score: float = 0
    budget_score: float = 0
    scene_score: float = 0
    keyword_match_score: float = 0
    logic_tag_match_score: float = 0
    memory_score: float = 0
    risk_penalty: float = 0


class ScoredPOICandidate(SafePOICandidate):
    final_poi_score: float = 0
    score_breakdown: POIScoreBreakdown = Field(default_factory=POIScoreBreakdown)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CandidateState(StateModel):
    recall_stats: RecallStats = Field(default_factory=RecallStats)
    raw_candidates: dict[str, list[SafePOICandidate]] = Field(default_factory=dict)
    scored_candidates: dict[str, list[ScoredPOICandidate]] = Field(default_factory=dict)
    balanced_candidates: dict[str, list[ScoredPOICandidate]] = Field(default_factory=dict)


class PlanSlot(StateModel):
    slot_id: str
    poi_id: str
    poi_name: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: int | None = None


class RouteSummary(StateModel):
    total_distance_km: float | None = None
    total_route_minutes: int | None = None
    max_pair_distance_km: float | None = None
    transport_mode: str | None = None


class PlanBudgetSummary(StateModel):
    estimated_total_budget: float | None = None
    estimated_per_person: float | None = None
    budget_fit: str = "unknown"


class TimelineItem(StateModel):
    time_text: str
    title: str
    description: str | None = None
    poi_id: str | None = None


class CandidatePlan(StateModel):
    plan_id: str
    generation_strategy: str
    slots: list[PlanSlot] = Field(default_factory=list)
    route_summary: RouteSummary = Field(default_factory=RouteSummary)
    budget_summary: PlanBudgetSummary = Field(default_factory=PlanBudgetSummary)
    estimated_timeline: list[TimelineItem] = Field(default_factory=list)


class POIAvailability(StateModel):
    open_status: str = "unknown"
    reservation_required: bool | None = None
    reservation_available: bool | None = None
    queue_risk: str | None = None
    ticket_available: str | None = None
    table_available: str | None = None
    source: str | None = None


class AvailabilityResults(StateModel):
    by_poi: dict[str, POIAvailability] = Field(default_factory=dict)


class VerificationIssue(StateModel):
    code: str
    severity: Literal["block", "warning", "info"] = "warning"
    message: str


class VerifiedPlan(StateModel):
    plan_id: str
    passed: bool
    blocking_issues: list[VerificationIssue] = Field(default_factory=list)
    warnings: list[VerificationIssue] = Field(default_factory=list)


class PlanRankFeatures(StateModel):
    preference_match: float = 0
    slot_coverage: float = 0
    distance_reasonable: float = 0
    time_feasible: float = 0
    rating_heat: float = 0
    budget_fit: float = 0
    scene_fit: float = 0
    memory_fit: float = 0
    warning_penalty: float = 0
    diversity_bonus: float = 0
    critic_penalty: float = 0


class RankedPlan(StateModel):
    plan_id: str
    rank: int
    plan_score: float
    rank_label: str
    rank_features: PlanRankFeatures = Field(default_factory=PlanRankFeatures)
    why_ranked_high: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)


class PlanResultsState(StateModel):
    planning_strategy: dict[str, Any] = Field(default_factory=dict)
    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    availability_results: AvailabilityResults = Field(default_factory=AvailabilityResults)
    verified_plans: list[VerifiedPlan] = Field(default_factory=list)
    ranked_plans: list[RankedPlan] = Field(default_factory=list)


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
        user_info=UserInfo(user_id=effective_user, city=city, geo_location=geo, default_origin=origin),
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
        selected_or_referenced_plan_id=str((state.get("selected_plan") or {}).get("id") or "") or None,
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
        "execution_status": "simulated" if payload.get("selected_plan") or payload.get("plans") else "pending",
        "intent_type": intent_type,
        "answer_mode": "simple_qa" if request_type == "simple_qa" else "trip_plan",
        "need_clarification": False,
        "missing_constraints": [],
        "clarify_question": "",
        "selected_plan": payload.get("selected_plan", {}),
        "ranked_plans": payload.get("plans", []),
        "errors": [*state.debug.errors, *response_issues],
        "logs": [trace.message or f"{trace.node}: {trace.status}" for trace in state.debug.node_trace],
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
        "origin_name": constraints.hard_constraints.origin.name if constraints.hard_constraints.origin else None,
        "required_slots": list(constraints.hard_constraints.required_slots),
        "avoid_keywords": list(constraints.hard_constraints.avoid_keywords),
        "duration_minutes": constraints.time_policy.duration_minutes,
        "duration_hours": (
            round(constraints.time_policy.duration_minutes / 60, 2)
            if constraints.time_policy.duration_minutes
            else None
        ),
        "start_time": constraints.time_policy.start_time.strftime("%H:%M") if constraints.time_policy.start_time else None,
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
