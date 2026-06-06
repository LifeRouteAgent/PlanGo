from __future__ import annotations

from app.core.exceptions import AppException, NoCandidatePOIException
from app.graph.intent_rules import detect_intent_type, detect_target_categories


def test_app_exception_has_standard_error_response() -> None:
    exc = AppException("TEST_ERROR", "测试错误", {"field": "x"})

    payload = exc.to_error_response(trace_id="trace_1")

    assert payload == {
        "success": False,
        "error": {
            "code": "TEST_ERROR",
            "message": "测试错误",
            "details": {"field": "x"},
        },
        "trace_id": "trace_1",
    }


def test_planning_exception_subclass_uses_stable_error_code() -> None:
    exc = NoCandidatePOIException()

    assert exc.error_code == "NO_CANDIDATE_POI"
    assert exc.to_error_response()["error"]["message"] == "没有可用候选 POI"


def test_intent_rules_moved_out_of_legacy_agents() -> None:
    assert detect_intent_type("推荐几个适合朋友聚会的餐厅") == "category_recommend"
    assert detect_target_categories("想吃火锅然后唱歌") == ["poi_restaurant", "poi_entertainment"]
