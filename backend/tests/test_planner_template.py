from __future__ import annotations

from app.planning.services import build_constraints, resolve_intent


def test_planning_template_maps_to_required_slots() -> None:
    understanding = resolve_intent("周末和朋友想先唱歌再吃饭，预算 300", {}, {})

    _, recall = build_constraints(understanding, city="北京", origin=None)

    assert "entertainment" in understanding.poi_recall_intent.target_logical_categories
    assert any("restaurant" in item.logical_categories for item in recall.slot_recall_requirements)
