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
    assert "周末本地生活轻量方案" in body["response_text"]
