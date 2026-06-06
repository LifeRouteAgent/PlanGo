from __future__ import annotations

import json
from pathlib import Path

from app.runtime.checkpoint_store import CheckpointStore, TaskStatus
from app.llm.output_schemas import (
    MemoryExtractionOutput,
    validate_llm_output,
)
from app.memory.memory_service import MemoryService
from app.planning.policy_config import policy_config
from app.tools.tool_policy import ToolCallRequest, ToolPolicy


class _NoopVectorStore:
    """测试用向量存储，避免单测依赖 Milvus。"""

    enabled = False
    available = False
    last_error = "disabled in unit test"

    def search_memory(self, *args, **kwargs):
        return []

    def upsert_memory(self, *args, **kwargs):
        return False

    def upsert_user_profile(self, *args, **kwargs):
        return False

    def search_similar_profiles(self, *args, **kwargs):
        return []

    def profile_clusters(self):
        return []

    def clear(self, *args, **kwargs):
        return None


def test_memory_profile_isolated_by_user_id() -> None:
    """不同 user_id 的画像文件必须隔离，不能再写全局 user_profile。"""

    memory = MemoryService(vector_store=_NoopVectorStore())
    user_a = "prod_user_a"
    user_b = "prod_user_b"
    memory.clear(user_id=user_a)
    memory.clear(user_id=user_b)

    profile_a = memory.read_profile(user_id=user_a)
    profile_a["preferred_city"] = "上海"
    memory._write_profile(profile_a, user_id=user_a)

    assert memory.read_profile(user_id=user_a)["preferred_city"] == "上海"
    assert memory.read_profile(user_id=user_b)["preferred_city"] == "北京"


def test_checkpoint_version_and_recovery_decisions() -> None:
    """Checkpoint 保存要有版本；已有成功交易后不能盲目重跑。"""

    store = CheckpointStore()
    task = store.create(
        session_id="prod_session",
        user_id="prod_user",
        trace_id="trace_prod",
        task_id="task_prod_hardening",
    )
    first_version = int(task["version"])
    task["status"] = TaskStatus.PLAN_VALIDATED.value
    store.save(task)
    saved = store.load("task_prod_hardening")

    assert saved is not None
    assert int(saved["version"]) > first_version

    store.append_action(
        "task_prod_hardening",
        {
            "action_id": "restaurant_1",
            "type": "restaurant_booking",
            "risk_level": 3,
            "status": "success",
            "idempotency_key": "idem_restaurant_1",
            "request": {},
            "result": {"ok": True},
        },
    )
    assert store.resume("task_prod_hardening")["decision"] == "require_user_confirmation"

    store.append_action(
        "task_prod_hardening",
        {
            "action_id": "ticket_1",
            "type": "ticket_order",
            "risk_level": 3,
            "status": "failed",
            "idempotency_key": "idem_ticket_1",
            "request": {},
            "result": {"ok": False},
        },
    )
    assert store.resume("task_prod_hardening")["decision"] == "compensate"


def test_tool_policy_requires_confirmation_source_for_level2_plus() -> None:
    """Level 2+ 工具不仅要确认，还要记录确认来源，便于审计。"""

    policy = ToolPolicy(validated_item_ids={"poi_1"})
    issues = policy.validate(
        ToolCallRequest(
            tool_name="restaurant_booking",
            risk_level=3,
            idempotency_key="idem_1",
            params={
                "target_id": "poi_1",
                "validated_item_ids": ["poi_1"],
                "confirmed": True,
            },
        )
    )
    assert any(issue["code"] == "validation_failed" for issue in issues)

    issues = policy.validate(
        ToolCallRequest(
            tool_name="restaurant_booking",
            risk_level=3,
            idempotency_key="idem_1",
            confirmed_source="execute_plan_button",
            params={
                "target_id": "poi_1",
                "validated_item_ids": ["poi_1"],
                "confirmed": True,
            },
        )
    )
    assert issues == []


def test_llm_schema_validation_rejects_invalid_payload() -> None:
    """LLM 输出必须过 schema，非法字段类型不能污染画像。"""

    result = validate_llm_output(
        MemoryExtractionOutput,
        {
            "should_update_profile": True,
            "scope": "long_term",
            "confidence": 1.5,
            "profile_updates": {"budget_level": "luxury"},
        },
        source="unit_test",
    )
    assert result.ok is False
    assert result.data == {}


def test_policy_configs_load_from_files() -> None:
    """策略配置应从文件加载，而不是散落在业务代码里。"""

    assert policy_config.planning_rules.max_segment_route_minutes > 0
    assert "restaurant_booking" in policy_config.risk_policy.risk_levels
    assert policy_config.category_policy.default_logical_categories


def test_local_life_benchmark_has_layered_paths() -> None:
    """固定 benchmark 要分层覆盖系统能力、上下文、记忆、恢复和业务效果。"""

    path = Path(__file__).parent / "evals" / "local_life_benchmark.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) >= 50
    layers = {case["layer"] for case in cases}
    assert {
        "harness_regression",
        "context_governance",
        "memory_benefit",
        "recovery_correctness",
        "business_effect",
    } <= layers
