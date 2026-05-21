from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app
from app.api.routes.trip import _build_agent_thinking_payload


def test_trip_plan_api_runs_langgraph_dag() -> None:
    """HTTP API 应能触发完整 LangGraph DAG，并返回模拟执行后的方案。"""

    client = TestClient(app)
    response = client.post(
        "/trip/plan",
        json={"user_query": "周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["execution_status"] == "simulated"
    assert body["selected_plan"]["id"] == "plan_mock_1"
    assert body["selected_plan"]["planning_template"] == "friends_gathering"
    assert body["selected_plan"]["plan_score"] > 0
    assert "score_breakdown" in body["selected_plan"]
    assert "朋友聚会本地生活方案" in body["response_text"]
    assert "方案评分：" in body["response_text"]
    assert "交通：" in body["response_text"]
    assert "时间线：" in body["response_text"]


def test_agent_thinking_payload_hides_internal_english_logs() -> None:
    """规划进度面板应展示中文标题和消息，而不是内部英文日志。"""

    events = [
        _build_agent_thinking_payload(
            "post_skill_router",
            {"logs": ["DAG: joined parallel skill results"]},
            {},
        ),
        _build_agent_thinking_payload(
            "availability_checker",
            {"logs": ["Availability Checker: all mock POIs are available"]},
            {},
        ),
        _build_agent_thinking_payload(
            "poi_lifestyle_recommend",
            {"recommended_pois": {"lifestyle": [{"id": "poi_1"}]}},
            {},
        ),
        _build_agent_thinking_payload(
            "poi_restaurant_recommend",
            {"recommended_pois": {"restaurant": []}},
            {},
        ),
        _build_agent_thinking_payload(
            "user_confirm",
            {"logs": ["User Confirm: auto-confirmed for the minimal DAG run"]},
            {},
        ),
        _build_agent_thinking_payload(
            "execution_agent",
            {
                "execution_status": "simulated",
                "logs": ["Execution Agent: execution_status=simulated"],
            },
            {},
        ),
    ]

    assert [event["title"] for event in events] == [
        "推荐汇总",
        "可用性检查",
        "生活方式 Skill",
        "餐厅推荐 Skill",
        "方案确认",
        "执行准备",
    ]
    assert all("DAG" not in event["message"] for event in events)
    assert all("Checker" not in event["message"] for event in events)
    assert all("User Confirm" not in event["message"] for event in events)
    assert all("Execution Agent" not in event["message"] for event in events)
    assert all("{" not in event["message"] for event in events)
    assert all("restaurant" not in event["message"] for event in events)
    assert all("lifestyle" not in event["message"] for event in events)
