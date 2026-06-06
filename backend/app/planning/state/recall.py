from app.planning.state.base import *  # noqa: F403

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

