from __future__ import annotations

from app.agents.llm_critic import llm_critic_node
from app.agents.planner_agent import planner_agent_node
from app.services.semantic_constraints import item_matches_keywords, semantic_keywords, semantic_types


def test_planner_prefers_llm_dag_plan() -> None:
    """Planner 应优先使用 Intent LLM 给出的 DAG Plan，而不是固定模板映射。"""

    state = {
        "user_query": "打麻将然后去唱歌",
        "intent_type": "full_trip_plan",
        "target_categories": ["poi_entertainment"],
        "constraints": {
            "duration_hours": 4,
            "llm_understanding": {
                "dag_plan": {
                    "collector_categories": ["poi_entertainment"],
                    "enabled_skills": ["poi_lifestyle_recommend"],
                    "planning_template": "entertainment_gathering",
                    "slot_sequence": ["entertainment", "optional_entertainment"],
                    "movement_policy": "low_movement",
                    "candidate_strategy": "preference_fit_first",
                    "reason": "朋友娱乐聚会",
                }
            },
        },
        "errors": [],
    }

    patch = planner_agent_node(state)  # type: ignore[arg-type]

    assert patch["dag_plan"]["planning_template"] == "entertainment_gathering"
    assert patch["dag_plan"]["enabled_skills"] == ["poi_lifestyle_recommend"]
    assert patch["dag_plan"]["slot_sequence"] == ["entertainment", "optional_entertainment"]
    assert patch["dag_plan"]["movement_policy"] == "low_movement"


def test_semantic_constraints_expose_llm_activity_intents() -> None:
    """Skill 层应通过结构化 activity_intents 匹配语义，而不是直接读 query。"""

    constraints = {
        "activity_intents": [{
            "slot": "entertainment",
            "semantic_type": "ktv",
            "must_match": True,
            "keywords": ["KTV", "唱歌"],
        }],
        "preference_keywords": ["包间"],
    }
    item = {"name": "欢乐 KTV", "subcategory": "娱乐", "tags": ["包间", "唱歌"]}

    assert semantic_types(constraints) == {"ktv"}
    assert "唱歌" in semantic_keywords(constraints)
    assert item_matches_keywords(item, semantic_keywords(constraints))


def test_llm_critic_merges_structured_issue(monkeypatch) -> None:
    """LLM Critic 输出的结构化 issue 应挂回对应方案并进入 errors。"""

    monkeypatch.setattr(
        "app.agents.llm_critic.call_chat_completion",
        lambda *args, **kwargs: """
        {
          "issues": [
            {
              "code": "pace_risk",
              "severity": "warning",
              "message": "第一站和第二站节奏偏紧。",
              "suggestion": "建议减少一个可选站点。",
              "target_plan_id": "p1",
              "target_item_id": "poi1",
              "confidence": 0.82
            }
          ]
        }
        """,
    )
    state = {
        "user_query": "周末和朋友出去玩",
        "constraints": {"scenario": "friends"},
        "errors": [],
        "verified_plans": [{
            "id": "p1",
            "title": "朋友聚会方案",
            "items": [{"id": "poi1", "name": "某 KTV", "category": "poi_entertainment"}],
            "timeline": [],
            "route_segments": [],
            "issues": [],
        }],
    }

    patch = llm_critic_node(state)  # type: ignore[arg-type]

    assert patch["errors"][0]["code"] == "pace_risk"
    assert patch["verified_plans"][0]["issues"][0]["target_item_id"] == "poi1"
