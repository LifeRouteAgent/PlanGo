from __future__ import annotations

from app.planning.state import FinalConstraints, SafePOICandidate
from app.planning.scoring_service import (
    budget_score,
    distance_score,
    keyword_score,
    quality_score,
    score_candidates,
    tag_score,
)


def test_poi_score_functions_are_deterministic() -> None:
    item = SafePOICandidate(
        poi_id="p1",
        name="室内 KTV",
        logical_category="entertainment",
        physical_table="poi_entertainment",
        logic_tags=["KTV", "室内"],
        distance_km=2,
        rating=4.5,
        avg_price=80,
    )

    assert quality_score(item.rating) == 0.9
    assert distance_score(item.distance_km, 10) == 0.8
    assert budget_score(item.avg_price, 100) == 1.0
    assert tag_score(item.logic_tags, ["KTV"]) == 1.0
    assert keyword_score(item, ["KTV"]) == 1.0


def test_score_candidates_outputs_breakdown_and_reasons() -> None:
    constraints = FinalConstraints()
    raw = {
        "entertainment": [
            SafePOICandidate(
                poi_id="p1",
                name="室内 KTV",
                logical_category="entertainment",
                physical_table="poi_entertainment",
                logic_tags=["KTV", "室内"],
                distance_km=2,
                rating=4.8,
                avg_price=120,
            )
        ]
    }

    scored = score_candidates(raw, constraints, ["KTV"])
    item = scored["entertainment"][0]

    assert item.final_poi_score > 0
    assert item.score_breakdown.distance_score > 0
    assert item.score_breakdown.memory_score > 0
    assert item.reasons
