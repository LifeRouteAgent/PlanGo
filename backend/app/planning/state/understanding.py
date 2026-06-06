from app.planning.state.base import *  # noqa: F403
from app.planning.state.context import PreferenceTag

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

