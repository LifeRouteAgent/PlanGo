from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.runtime.runtime_paths import POLICY_CONFIG_DIR
from app.observability.trace_recorder import record_trace_event


class PlanningRulesConfig(BaseModel):
    """规划阶段的数值阈值和默认时长配置。"""

    default_start_hour: int = Field(default=10, ge=0, le=23)
    default_total_duration_minutes: int = Field(default=240, ge=30)
    max_route_minutes: int = Field(default=90, ge=0)
    max_segment_route_minutes: int = Field(default=45, ge=0)
    top_k_per_category: int = Field(default=8, ge=1, le=50)
    max_raw_plan_combinations: int = Field(default=12, ge=1, le=200)
    default_budget_per_person: int = Field(default=180, ge=0)
    stay_minutes_by_slot: dict[str, int] = Field(default_factory=dict)


class CategoryPolicyConfig(BaseModel):
    """模板、slot 和 V2 逻辑类别映射。"""

    template_slots: dict[str, list[str]] = Field(default_factory=dict)
    slot_categories: dict[str, list[str]] = Field(default_factory=dict)
    default_logical_categories: list[str] = Field(default_factory=list)


class RiskPolicyConfig(BaseModel):
    """工具风险等级和确认边界。"""

    risk_levels: dict[str, int] = Field(default_factory=dict)
    requires_confirmation_min_level: int = Field(default=2, ge=0, le=4)
    requires_verified_target_min_level: int = Field(default=3, ge=0, le=4)
    auto_execute_max_level: int = Field(default=3, ge=0, le=4)

    def risk_level_for(self, action_type: str, *, default: int = 1) -> int:
        """读取动作风险等级，缺失时按查询类工具处理。"""

        try:
            return int(self.risk_levels.get(action_type, default))
        except (TypeError, ValueError):
            return default


class PolicyConfigService:
    """集中加载策略配置。

    当前配置文件使用 JSON-compatible YAML，避免新增 PyYAML 依赖；如果文件缺失或
    格式错误，服务会回退到 Pydantic 默认值，并把原因写入 trace。
    """

    @cached_property
    def planning_rules(self) -> PlanningRulesConfig:
        return _load_config("planning_rules.yaml", PlanningRulesConfig)

    @cached_property
    def category_policy(self) -> CategoryPolicyConfig:
        return _load_config("category_policy.yaml", CategoryPolicyConfig)

    @cached_property
    def risk_policy(self) -> RiskPolicyConfig:
        return _load_config("risk_policy.yaml", RiskPolicyConfig)


def _load_config(file_name: str, model: type[BaseModel]) -> Any:
    path = POLICY_CONFIG_DIR / file_name
    if not path.exists():
        record_trace_event(
            "policy_config_fallback",
            {"file": str(path), "reason": "missing"},
        )
        return model()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return model.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        record_trace_event(
            "policy_config_fallback",
            {"file": str(path), "reason": str(exc)[:500]},
        )
        return model()


policy_config = PolicyConfigService()
