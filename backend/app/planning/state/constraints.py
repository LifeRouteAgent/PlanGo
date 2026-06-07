from app.planning.state.base import *  # noqa: F403
from app.planning.state.context import OriginPoint


class HardConstraints(StateModel):
    city: str | None = None
    origin: OriginPoint | None = None
    avoid_keywords: list[str] = Field(default_factory=list)
    required_slots: list[str] = Field(default_factory=list)
    slot_duration_minutes: dict[str, int] = Field(default_factory=dict)
    slot_logical_categories: dict[str, list[str]] = Field(default_factory=dict)
    slot_names: dict[str, str] = Field(default_factory=dict)
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
