from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppException(Exception):
    """应用统一异常基类。

    业务层抛出的异常应携带稳定 error_code 和用户可见 message；
    details 只放脱敏后的调试上下文，避免把 SQL、密钥、精确位置透出到 API。
    """

    error_code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def to_error_response(self, trace_id: str = "") -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": self.error_code,
                "message": self.message,
                "details": self.details,
            },
            "trace_id": trace_id,
        }


class ValidationException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("VALIDATION_ERROR", message, details or {})


class LLMOutputParseException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("LLM_OUTPUT_PARSE_ERROR", message, details or {})


class ToolCallException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("TOOL_CALL_ERROR", message, details or {})


class RepositoryException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("REPOSITORY_ERROR", message, details or {})


class PlanningException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("PLANNING_ERROR", message, details or {})


class NoCandidatePOIException(PlanningException):
    def __init__(self, message: str = "没有可用候选 POI", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details or {})
        self.error_code = "NO_CANDIDATE_POI"


class RoutePlanningException(PlanningException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details or {})
        self.error_code = "ROUTE_PLANNING_ERROR"


class VerificationException(PlanningException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details or {})
        self.error_code = "VERIFICATION_ERROR"


class ExternalServiceException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("EXTERNAL_SERVICE_ERROR", message, details or {})
