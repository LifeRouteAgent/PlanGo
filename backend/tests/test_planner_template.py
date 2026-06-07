from __future__ import annotations

from app.planning.services import build_constraints, resolve_intent
from app.planning.state import (
    IntentResult,
    LLMUnderstanding,
    POIRecallIntent,
    SceneUnderstanding,
    SlotDetail,
    SlotUnderstanding,
)


def test_dynamic_slots_drive_recall_requirements() -> None:
    understanding = resolve_intent("周末和朋友想先唱歌再吃饭，预算 300", {}, {})

    _, recall = build_constraints(understanding, city="北京", origin=None)

    assert "entertainment" in understanding.poi_recall_intent.target_logical_categories
    assert any("restaurant" in item.logical_categories for item in recall.slot_recall_requirements)
    assert recall.target_slots == understanding.slots.required_slots


def test_unspecified_total_duration_comes_from_dynamic_slots() -> None:
    understanding = LLMUnderstanding(
        raw_user_message="下午安排两个活动",
        intent=IntentResult(request_type="full_itinerary_plan"),
        scene=SceneUnderstanding(scene_type="custom"),
        slots=SlotUnderstanding(
            required_slots=["slot_1", "slot_2"],
            slot_details=[
                SlotDetail(
                    slot_id="slot_1",
                    slot_name="展览",
                    slot_type="activity",
                    candidate_logical_categories=["activity"],
                    expected_duration_minutes=60,
                ),
                SlotDetail(
                    slot_id="slot_2",
                    slot_name="唱歌",
                    slot_type="entertainment",
                    candidate_logical_categories=["entertainment"],
                    expected_duration_minutes=120,
                ),
            ],
        ),
        poi_recall_intent=POIRecallIntent(
            target_logical_categories=["activity", "entertainment"]
        ),
    )

    constraints, recall = build_constraints(understanding, city="北京", origin=None)

    assert constraints.hard_constraints.slot_duration_minutes == {"slot_1": 60, "slot_2": 120}
    assert constraints.time_policy.duration_minutes == 200
    assert recall.target_slots == ["slot_1", "slot_2"]
