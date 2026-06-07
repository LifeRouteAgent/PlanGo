from app.planning.state.base import *  # noqa: F403

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


class SessionSummary(StateModel):
    summary: str = ""
    active_constraints: dict[str, Any] = Field(default_factory=dict)
    negative_constraints: list[str] = Field(default_factory=list)
    resolved_references: dict[str, Any] = Field(default_factory=dict)
    current_focus: str = ""
    last_plan_ids: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class ConversationContext(StateModel):
    history_summary: str | None = None
    session_summary: SessionSummary = Field(default_factory=SessionSummary)
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
    prompt_context_pack: dict[str, Any] = Field(default_factory=dict)

