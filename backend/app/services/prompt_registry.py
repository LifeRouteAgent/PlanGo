from __future__ import annotations

from dataclasses import dataclass

from app.services.trace_recorder import record_trace_event


@dataclass(frozen=True)
class PromptSpec:
    """LLM prompt 版本声明。"""

    prompt_name: str
    prompt_version: str
    schema_name: str
    schema_version: str


PROMPT_SPECS: dict[str, PromptSpec] = {
    "intent_understanding": PromptSpec("intent_understanding", "2026-05-31.1", "IntentUnderstandingOutput", "1"),
    "revision_parser": PromptSpec("revision_parser", "2026-05-31.1", "RevisionConstraintOutput", "1"),
    "memory_extractor": PromptSpec("memory_extractor", "2026-05-31.1", "MemoryExtractionOutput", "1"),
    "planner_dag": PromptSpec("planner_dag", "2026-05-31.1", "DagPlanOutput", "1"),
    "llm_critic": PromptSpec("llm_critic", "2026-05-31.1", "CriticOutput", "1"),
    "response_plan_enrichment": PromptSpec("response_plan_enrichment", "2026-05-31.1", "ResponsePlansEnrichmentOutput", "1"),
    "response_generator": PromptSpec("response_generator", "2026-05-31.1", "ResponseEnrichmentOutput", "1"),
}


def get_prompt_spec(prompt_name: str | None) -> PromptSpec:
    """获取 prompt 版本，未知 prompt 会记录 trace 并返回 ad_hoc 规格。"""

    name = (prompt_name or "").strip()
    if name in PROMPT_SPECS:
        return PROMPT_SPECS[name]
    record_trace_event("prompt_version_missing", {"prompt_name": prompt_name or ""})
    return PromptSpec(name or "ad_hoc", "unversioned", "unknown", "0")
