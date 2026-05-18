from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app


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
