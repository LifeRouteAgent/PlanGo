from __future__ import annotations

from app.dag.langgraph_dag_config import life_route_graph
from app.state.plan_state import create_initial_state


def test_capability_question_skips_planning_dag() -> None:
    """用户问系统能力时，应直接回答，不启动 Collector/Route/Execution。"""

    result = life_route_graph.invoke(create_initial_state("你能做什么？"))

    assert result["intent_type"] == "capability"
    assert result["execution_status"] == "pending"
    assert "完整行程规划" in result["response_text"]
    assert not any("POI Collector" in log for log in result["logs"])


def test_category_recommendation_uses_lightweight_recommendation_path() -> None:
    """只推荐餐厅时，应走分类推荐轻路径，不生成行程时间线。"""

    result = life_route_graph.invoke(create_initial_state("推荐几个适合朋友聚会的餐厅"))

    assert result["intent_type"] == "category_recommend"
    assert result["target_categories"] == ["poi_restaurant"]
    assert result["execution_status"] == "pending"
    assert result["selected_plan"]["id"] == "category_recommendation"
    assert "为你推荐这些本地生活地点" in result["response_text"]
    assert any("POI Collector" in log for log in result["logs"])
    assert not any("Route & Time Planner" in log for log in result["logs"])


def test_full_trip_plan_still_runs_execution_path() -> None:
    """完整行程请求仍应走原有规划、校验、排序和模拟执行链路。"""

    result = life_route_graph.invoke(
        create_initial_state("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")
    )

    assert result["intent_type"] == "full_trip_plan"
    assert result["execution_status"] == "simulated"
    assert result["selected_plan"]["id"] == "plan_mock_1"
    assert any("Route & Time Planner" in log for log in result["logs"])


def test_vague_full_trip_plan_asks_for_clarification() -> None:
    """完整规划条件不足时，应先追问，不读取数据库也不生成路线。"""

    result = life_route_graph.invoke(create_initial_state("周末想出去玩"))

    assert result["intent_type"] == "full_trip_plan"
    assert result["need_clarification"] is True
    assert result["execution_status"] == "pending"
    assert "people_or_scenario" in result["missing_constraints"]
    assert "preference" in result["missing_constraints"]
    assert result["answer_mode"] == "clarification"
    assert "还需要确认" in result["response_text"]
    assert not any("POI Collector" in log for log in result["logs"])
    assert not any("Route & Time Planner" in log for log in result["logs"])


def test_specific_full_trip_plan_skips_clarification() -> None:
    """人数、时间和偏好都明确时，不应打断用户继续追问。"""

    result = life_route_graph.invoke(
        create_initial_state("周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600，别太远")
    )

    assert result["intent_type"] == "full_trip_plan"
    assert result["need_clarification"] is False
    assert result["execution_status"] == "simulated"
    assert any("POI Collector" in log for log in result["logs"])


def test_mahjong_and_singing_query_infers_entertainment_preference() -> None:
    """麻将、打牌、唱歌都属于休闲娱乐偏好，不应触发 preference 追问。"""

    result = life_route_graph.invoke(
        create_initial_state("周末上午和朋友出去玩 4 个小时，想去打麻将打牌然后去唱歌，预算200")
    )

    assert result["intent_type"] == "full_trip_plan"
    assert result["target_categories"] == ["poi_entertainment"]
    assert result["need_clarification"] is False
    assert result["constraints"]["preferences"] == ["休闲娱乐"]
    assert result["dag_plan"]["planning_template"] == "entertainment_gathering"
    assert result["execution_status"] == "simulated"
    assert result["selected_plan"]["estimated_budget"] <= 200
    assert any("POI Collector" in log for log in result["logs"])
    assert any("Route & Time Planner" in log for log in result["logs"])


def test_llm_understanding_drives_intent_parser_clarifier_and_planner(monkeypatch) -> None:
    """大模型返回结构化理解时，Router/Parser/Clarifier/Planner 应优先使用模型结果。"""

    def fake_understanding(query: str, user_profile: dict) -> dict:
        return {
            "intent_type": "full_trip_plan",
            "target_categories": ["poi_entertainment"],
            "scenario": "friends",
            "people_count": 4,
            "preferences": ["麻将", "唱歌"],
            "location_area": "朝阳区",
            "start_time": "10:00",
            "duration_hours": 4,
            "budget": 200,
            "planning_template": "entertainment_gathering",
            "required_slots": ["entertainment", "optional_entertainment"],
            "need_clarification": False,
            "missing_constraints": [],
            "clarify_question": "",
        }

    monkeypatch.setattr("app.agents.intent_router.build_llm_understanding", fake_understanding)

    result = life_route_graph.invoke(create_initial_state("周末上午出去玩"))

    assert result["intent_type"] == "full_trip_plan"
    assert result["target_categories"] == ["poi_entertainment"]
    assert result["constraints"]["scenario"] == "friends"
    assert result["constraints"]["people_count"] == 4
    assert result["constraints"]["budget"] == 200
    assert result["constraints"]["location_area"] == "朝阳区"
    assert result["need_clarification"] is False
    assert result["dag_plan"]["planning_template"] == "entertainment_gathering"
    assert result["dag_plan"]["required_slots"] == ["entertainment", "optional_entertainment"]
    assert any("Intent Router: used LLM understanding" in log for log in result["logs"])
    assert any("Intent Parser: used LLM" in log for log in result["logs"])
    assert any("Constraint Clarifier: used LLM" in log for log in result["logs"])
    assert any("Planner Agent: used LLM template" in log for log in result["logs"])


def test_rule_guard_prevents_llm_from_downgrading_clear_plan(monkeypatch) -> None:
    """模型误判为闲聊时，规则护栏不能让明确规划请求被降级。"""

    def bad_understanding(query: str, user_profile: dict) -> dict:
        return {
            "intent_type": "simple_qa",
            "target_categories": [],
            "scenario": "unknown",
            "people_count": None,
            "preferences": [],
            "location_area": None,
            "start_time": None,
            "duration_hours": None,
            "budget": None,
            "planning_template": "",
            "required_slots": [],
            "need_clarification": False,
            "missing_constraints": [],
            "clarify_question": "",
        }

    monkeypatch.setattr("app.agents.intent_router.build_llm_understanding", bad_understanding)

    result = life_route_graph.invoke(
        create_initial_state("周末上午和朋友出去玩 4 个小时，想去打麻将打牌然后去唱歌，预算200")
    )

    assert result["intent_type"] == "full_trip_plan"
    assert result["target_categories"] == ["poi_entertainment"]
    assert result["need_clarification"] is False
    assert result["execution_status"] == "simulated"
    assert any("guarded_from=simple_qa" in log for log in result["logs"])
