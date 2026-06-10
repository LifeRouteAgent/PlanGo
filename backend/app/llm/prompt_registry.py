from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.observability.trace_recorder import TraceRecorder

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


@dataclass(frozen=True)
class PromptSpec:
    """LLM prompt 版本声明。"""

    prompt_name: str
    prompt_version: str
    schema_name: str
    schema_version: str


PROMPT_SPECS: dict[str, PromptSpec] = {
    "intent_understanding": PromptSpec(
        "intent_understanding", "2026-05-31.1", "IntentUnderstandingOutput", "1"
    ),
    "revision_parser": PromptSpec(
        "revision_parser", "2026-05-31.1", "RevisionConstraintOutput", "1"
    ),
    "memory_extractor": PromptSpec(
        "memory_extractor", "2026-05-31.1", "MemoryExtractionOutput", "1"
    ),
    "session_summary": PromptSpec("session_summary", "2026-06-07.1", "SessionSummaryOutput", "1"),
    "response_generation_package": PromptSpec(
        "response_generation_package", "2026-06-03.1", "ResponseGenerationOutput", "1"
    ),
}


def get_prompt_spec(prompt_name: str | None) -> PromptSpec:
    """获取 prompt 版本，未知 prompt 会记录 trace 并返回 ad_hoc 规格。"""

    name = (prompt_name or "").strip()
    if name in PROMPT_SPECS:
        return PROMPT_SPECS[name]
    TraceRecorder.record("prompt_version_missing", {"prompt_name": prompt_name or ""})
    return PromptSpec(name or "ad_hoc", "unversioned", "unknown", "0")


def load_prompt_template(prompt_name: str, fallback: str = "") -> str:
    """从 app/prompts 读取外置 prompt 模板。

    Prompt 文本外置后，版本对比、评审和灰度会比散落在代码字符串里更清晰。
    如果文件不存在，记录 trace 并返回调用方提供的 fallback。
    """

    path = PROMPT_DIR / f"{prompt_name}.md"
    if not path.exists():
        TraceRecorder.record(
            "prompt_template_missing", {"prompt_name": prompt_name, "path": str(path)}
        )
        return fallback
    return path.read_text(encoding="utf-8").strip()
