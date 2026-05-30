from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Literal, TypedDict

from app.services.checkpoint_store import make_idempotency_key

RiskLevelValue = Literal[0, 1, 2, 3, 4]


class RiskLevel(IntEnum):
    """工具风险等级。"""

    INTERNAL = 0
    QUERY = 1
    LIGHT_MUTATION = 2
    TRANSACTION = 3
    PAYMENT = 4


class ToolFailureCode(StrEnum):
    """统一工具失败分类。"""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SLOT_UNAVAILABLE = "slot_unavailable"
    NOT_FOUND = "not_found"
    PAYMENT_REQUIRED = "payment_required"
    PERMISSION_DENIED = "permission_denied"
    PARTIAL_SUCCESS = "partial_success"
    VALIDATION_FAILED = "validation_failed"
    TARGET_NOT_VERIFIED = "target_not_verified"
    UNKNOWN = "unknown"


class ToolCallRequest(TypedDict, total=False):
    """统一工具调用请求。"""

    tool_name: str
    risk_level: int
    user_id: str
    session_id: str
    task_id: str
    idempotency_key: str | None
    params: dict[str, Any]
    requires_confirmation: bool
    confirmed: bool
    confirmed_source: str


class ToolCallResult(TypedDict, total=False):
    """统一工具调用结果。"""

    success: bool
    data: dict[str, Any] | str | list[Any] | None
    error_code: str | None
    source: str
    fetched_at: str
    expires_at: str | None
    confidence: float
    fallback_used: bool
    attempts: int
    latency_ms: int


@dataclass
class ToolPolicy:
    """工具调用策略与参数校验。

    查询类工具可以自动执行；轻状态变更和交易类工具必须有用户确认语义；
    交易类工具还必须有幂等键，并且目标来自已验证候选或当前方案。
    """

    validated_plan_ids: set[str] = field(default_factory=set)
    validated_item_ids: set[str] = field(default_factory=set)
    confirmed_action_ids: set[str] = field(default_factory=set)

    def requires_confirmation(self, risk_level: int) -> bool:
        """Level 2+ 需要用户总确认；Level 4 永不自动执行。"""

        return int(risk_level) >= RiskLevel.LIGHT_MUTATION

    def validate(self, request: ToolCallRequest) -> list[dict[str, Any]]:
        """校验工具参数和权限边界。"""

        issues: list[dict[str, Any]] = []
        risk_level = int(request.get("risk_level", RiskLevel.QUERY))
        params = request.get("params", {}) or {}
        confirmed = bool(request.get("confirmed") or params.get("confirmed"))
        confirmed_source = str(
            request.get("confirmed_source")
            or params.get("confirmed_source")
            or params.get("confirmation_source")
            or ""
        )

        if risk_level >= RiskLevel.LIGHT_MUTATION and not confirmed:
            issues.append(_issue("permission_denied", "高风险工具缺少用户确认。"))
        if risk_level >= RiskLevel.LIGHT_MUTATION and confirmed and not confirmed_source:
            issues.append(_issue("validation_failed", "Level 2+ 工具必须记录确认来源。"))
        if risk_level == RiskLevel.PAYMENT:
            issues.append(_issue("payment_required", "支付/退款工具 v1 不允许自动执行。"))
        if risk_level >= RiskLevel.TRANSACTION and not request.get("idempotency_key"):
            issues.append(_issue("validation_failed", "交易工具缺少 idempotency_key。"))

        issues.extend(_validate_common_params(params))

        if risk_level >= RiskLevel.TRANSACTION:
            target_id = str(params.get("target_id") or params.get("poi_id") or "")
            validated_item_ids = self.validated_item_ids or {
                str(item) for item in params.get("validated_item_ids", []) if str(item)
            }
            if not target_id or (validated_item_ids and target_id not in validated_item_ids):
                issues.append(_issue("target_not_verified", "交易目标必须来自已验证候选。"))
        return issues

    def ensure_idempotency_key(self, request: ToolCallRequest) -> str:
        """为交易工具补齐幂等键。"""

        if request.get("idempotency_key"):
            return str(request["idempotency_key"])
        params = request.get("params", {}) or {}
        return make_idempotency_key(
            user_id=str(request.get("user_id") or "default"),
            task_id=str(request.get("task_id") or ""),
            action_type=str(request.get("tool_name") or ""),
            target_id=str(params.get("target_id") or params.get("poi_id") or ""),
            slot_time=str(params.get("slot_time") or params.get("start_time") or ""),
            amount=params.get("amount", ""),
        )

    def classify_error(self, error: str | None) -> str:
        """把异常文本归一为业务失败分类。"""

        text = (error or "").lower()
        if "timeout" in text or "timed out" in text:
            return ToolFailureCode.TIMEOUT.value
        if "rate" in text or "429" in text:
            return ToolFailureCode.RATE_LIMITED.value
        if "slot" in text or "unavailable" in text or "sold out" in text:
            return ToolFailureCode.SLOT_UNAVAILABLE.value
        if "not found" in text or "404" in text:
            return ToolFailureCode.NOT_FOUND.value
        if "payment" in text or "pay" in text:
            return ToolFailureCode.PAYMENT_REQUIRED.value
        if "permission" in text or "denied" in text or "unauthorized" in text:
            return ToolFailureCode.PERMISSION_DENIED.value
        if "partial" in text:
            return ToolFailureCode.PARTIAL_SUCCESS.value
        return ToolFailureCode.UNKNOWN.value


def tool_request_hash(request: ToolCallRequest) -> str:
    """生成工具请求 hash，用于缓存和重复调用检测。"""

    raw = json.dumps(request, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _validate_common_params(params: dict[str, Any]) -> list[dict[str, Any]]:
    """校验所有工具共享的基础参数。"""

    issues: list[dict[str, Any]] = []
    if "people_count" in params:
        try:
            count = int(params["people_count"])
            if count <= 0 or count > 50:
                issues.append(_issue("validation_failed", "人数必须在 1-50 之间。"))
        except (TypeError, ValueError):
            issues.append(_issue("validation_failed", "人数必须是数字。"))
    if "budget" in params:
        try:
            if float(params["budget"]) < 0:
                issues.append(_issue("validation_failed", "预算不能为负数。"))
        except (TypeError, ValueError):
            issues.append(_issue("validation_failed", "预算必须是数字。"))
    for lat_key, lon_key in (("lat", "lon"), ("origin_lat", "origin_lon")):
        if lat_key in params or lon_key in params:
            try:
                lat = float(params[lat_key])
                lon = float(params[lon_key])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    issues.append(_issue("validation_failed", "经纬度超出合法范围。"))
            except (KeyError, TypeError, ValueError):
                issues.append(_issue("validation_failed", "经纬度必须成对提供且为数字。"))
    return issues


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}
