from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.observability.trace_recorder import record_trace_event


class LLMSchemaValidationResult(BaseModel):
    """LLM 结构化输出校验结果。"""

    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    schema_name: str


class MemoryProfileUpdates(BaseModel):
    """长期画像可写字段，避免 LLM 输出任意键污染画像。"""

    indoor_preference: bool | None = None
    budget_level: Literal["low", "medium", "high"] | None = None
    preferred_areas: list[str] = Field(default_factory=list)
    favorite_categories: list[str] = Field(default_factory=list)
    disliked_keywords: list[str] = Field(default_factory=list)


class MemoryExtractionOutput(BaseModel):
    should_update_profile: bool = False
    scope: Literal["temporary", "long_term"] = "temporary"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    profile_updates: MemoryProfileUpdates = Field(default_factory=MemoryProfileUpdates)
    memory_text: str = ""
    tags: list[str] = Field(default_factory=list)


class ActivityIntentOutput(BaseModel):
    slot: str = ""
    semantic_type: str = ""
    must_match: bool = False
    keywords: list[str] = Field(default_factory=list)


class CategoryTagRequirementOutput(BaseModel):
    logical_category: str
    target_slot: str = ""
    positive_logic_tags: list[str] = Field(default_factory=list)
    negative_logic_tags: list[str] = Field(default_factory=list)


class DynamicSlotOutput(BaseModel):
    slot_id: str = ""
    slot_type: str = ""
    slot_name: str = ""
    required: bool = True
    candidate_logical_categories: list[str] = Field(default_factory=list)
    max_duration_minutes: int | None = Field(default=None, ge=0)
    keywords: list[str] = Field(default_factory=list)
    reason: str = ""


class RevisionConstraintOutput(BaseModel):
    revision_type: str = "global_constraint"
    indoor_preferred: bool | None = None
    avoid_tags: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    budget_strategy: str | None = None
    budget: int | None = Field(default=None, ge=0)
    price_preference: str | None = None
    max_route_minutes: int | None = Field(default=None, ge=0)
    movement_policy: str | None = None
    preferred_categories: list[str] = Field(default_factory=list)
    activity_intents: list[ActivityIntentOutput] = Field(default_factory=list)
    reason: str = ""


class FollowupContextOutput(BaseModel):
    current_turn_type: Literal[
        "direct_answer",
        "new_request",
        "clarification_answer",
        "planning_revision",
    ] = "new_request"
    should_merge_previous_planning: bool = False
    use_pending_clarification: bool = False
    reason: str = ""


class DagPlanOutput(BaseModel):
    collector_categories: list[str] = Field(default_factory=list)
    planning_template: str = ""
    slot_sequence: list[str] = Field(default_factory=list)
    dynamic_slots: list[DynamicSlotOutput] = Field(default_factory=list)
    movement_policy: str = ""
    candidate_strategy: str = ""
    reason: str = ""


class MustPoiOutput(BaseModel):
    name: str
    category: str | None = None
    must_include: bool = True


class IntentUnderstandingOutput(BaseModel):
    intent_type: str
    target_categories: list[str] = Field(default_factory=list)
    scenario: str | None = None
    people_count: int | None = Field(default=None, ge=1)
    preferences: list[str] = Field(default_factory=list)
    location_area: str | None = None
    start_time: str | None = None
    duration_hours: float | None = Field(default=None, ge=0)
    budget: int | None = Field(default=None, ge=0)
    planning_template: str | None = None
    required_slots: list[str] = Field(default_factory=list)
    dynamic_slots: list[DynamicSlotOutput] = Field(default_factory=list)
    must_pois: list[MustPoiOutput] = Field(default_factory=list)
    preference_keywords: list[str] = Field(default_factory=list)
    activity_intents: list[ActivityIntentOutput] = Field(default_factory=list)
    category_tag_requirements: list[CategoryTagRequirementOutput] = Field(default_factory=list)
    dag_plan: DagPlanOutput | None = None
    need_clarification: bool = False
    missing_constraints: list[str] = Field(default_factory=list)
    clarify_question: str = ""


class CriticIssueOutput(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    suggestion: str = ""
    target_plan_id: str | None = None
    target_item_id: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CriticOutput(BaseModel):
    issues: list[CriticIssueOutput] = Field(default_factory=list)


class ResponseEnrichmentOutput(BaseModel):
    response_text: str = ""
    plan_reasons: dict[str, str] = Field(default_factory=dict)
    option_prompts: dict[str, list[str]] = Field(default_factory=dict)


class ResponseItemEnrichmentOutput(BaseModel):
    id: str
    recommendation_reason: str = ""
    option_prompts: list[str] = Field(default_factory=list)


class ResponsePlanActionOutput(BaseModel):
    id: str
    label: str
    type: Literal["execute", "export", "refine"] = "refine"
    prompt: str = ""


class ResponsePlanEnrichmentOutput(BaseModel):
    id: str
    title: str = ""
    recommendation_reason: str = ""
    highlight_tags: list[str] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    plan_actions: list[ResponsePlanActionOutput] = Field(default_factory=list)
    items: list[ResponseItemEnrichmentOutput] = Field(default_factory=list)


class ResponsePlansEnrichmentOutput(BaseModel):
    plans: list[ResponsePlanEnrichmentOutput] = Field(default_factory=list)


class ResponseGenerationOutput(BaseModel):
    """响应生成统一输出：一次 LLM 同时产出最终回复和方案展示增强。"""

    response_text: str = ""
    plans: list[ResponsePlanEnrichmentOutput] = Field(default_factory=list)


def validate_llm_output(
    schema: type[BaseModel],
    payload: Any,
    *,
    source: str,
) -> LLMSchemaValidationResult:
    """校验 LLM JSON 输出，失败时记录 trace 并返回空数据。"""

    try:
        model = schema.model_validate(payload)
        data = model.model_dump()
        record_trace_event(
            "llm_schema_validated",
            {"source": source, "schema": schema.__name__, "ok": True},
        )
        return LLMSchemaValidationResult(ok=True, data=data, schema_name=schema.__name__)
    except ValidationError as exc:
        record_trace_event(
            "schema_validation_failed",
            {
                "source": source,
                "schema": schema.__name__,
                "error": str(exc)[:1200],
                "payload_preview": str(payload)[:1200],
            },
        )
        return LLMSchemaValidationResult(
            ok=False,
            data={},
            error=str(exc),
            schema_name=schema.__name__,
        )

