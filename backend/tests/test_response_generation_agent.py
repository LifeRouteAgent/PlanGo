from __future__ import annotations

from app.llm_agents.response_generation_agent import (
    apply_response_generation,
    compact_payload_for_llm,
)
from app.graph.nodes.response_nodes import response_generator_node
from app.graph.state import create_planning_state


def _payload() -> dict:
    return {
        "response_type": "plan_cards",
        "summary": "已生成方案",
        "debug": {"sql": "select * from secret"},
        "plans": [
            {
                "id": "plan_1",
                "plan_id": "plan_1",
                "title": "旧标题",
                "tags": ["娱乐"],
                "pros": ["旧优点"],
                "cons": ["旧注意"],
                "route_text": "交通约 12 分钟",
                "budget_text": "预计约 200 元",
                "route_segments": [{"polyline": [{"lat": 39.9, "lng": 116.4}]}],
                "items": [
                    {
                        "id": "poi_1",
                        "name": "测试 KTV",
                        "display_category": "娱乐",
                        "lat": 39.9,
                        "lon": 116.4,
                        "tags": ["KTV", "室内"],
                        "raw_extra": {"sql": "hidden"},
                    }
                ],
            }
        ],
        "selected_plan": {"id": "plan_1"},
    }


def test_compact_payload_for_llm_excludes_sensitive_fields() -> None:
    compact = compact_payload_for_llm(_payload())
    text = str(compact)

    assert "lat" not in text
    assert "lon" not in text
    assert "polyline" not in text
    assert "raw_extra" not in text
    assert "select *" not in text
    assert compact["plans"][0]["items"][0]["name"] == "测试 KTV"


def test_apply_response_generation_only_changes_display_fields() -> None:
    payload = _payload()
    generation = {
        "response_text": "这里有两条轻松路线。",
        "plans": [
            {
                "id": "plan_1",
                "title": "微醺欢唱线",
                "highlight_tags": ["欢唱", "室内"],
                "tags": ["欢唱", "室内"],
                "pros": ["室内不晒", "路线轻松"],
                "cons": ["需确认预约"],
                "items": [{"id": "poi_1", "recommendation_reason": "适合朋友聚会"}],
            }
        ],
    }

    result = apply_response_generation(payload, generation)
    plan = result["plans"][0]

    assert result["_llm_final_text"] == "这里有两条轻松路线。"
    assert plan["title"] == "微醺欢唱线"
    assert plan["pros"] == ["室内不晒", "路线轻松"]
    assert plan["items"][0]["id"] == "poi_1"
    assert plan["items"][0]["lat"] == 39.9
    assert plan["route_segments"][0]["polyline"]


def test_response_generator_node_uses_llm_display_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.graph.nodes.response_nodes.generate_response_package",
        lambda payload: {
            "response_text": "LLM 生成的最终回复",
            "plans": [
                {
                    "id": "plan_1",
                    "title": "欢唱小聚线",
                    "highlight_tags": ["欢唱"],
                    "tags": ["欢唱"],
                    "pros": ["气氛轻松"],
                    "cons": ["需先预约"],
                }
            ],
        },
    )
    state = create_planning_state("测试")
    response = state.response.model_copy(deep=True)
    response.response_payload = {
        "response_type": "plan_cards",
        "summary": "已生成方案",
        "plans": [
            {
                "id": "plan_1",
                "plan_id": "plan_1",
                "title": "旧标题",
                "items": [
                    {
                        "id": "poi_1",
                        "name": "测试 KTV",
                        "category": "poi_entertainment",
                        "logical_category": "entertainment",
                        "tags": ["KTV"],
                    }
                ],
            }
        ],
        "selected_plan": {"id": "plan_1"},
    }
    state.response = response

    patch = response_generator_node(state)
    payload = patch["response"].response_payload

    assert patch["response"].final_text == "LLM 生成的最终回复"
    assert payload["plans"][0]["title"] == "欢唱小聚线"
    assert payload["plans"][0]["pros"] == ["气氛轻松"]
