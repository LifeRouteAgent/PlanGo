from datetime import datetime
from typing import Literal, Any

from pydantic import Field

from app.planning.state import StateModel


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
