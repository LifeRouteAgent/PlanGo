from __future__ import annotations

from app.planning.services import create_route_plans
from app.planning.state import FinalConstraints, HardConstraints, ScoredPOICandidate


def _poi(poi_id: str, lat: float, lng: float, category: str) -> ScoredPOICandidate:
    return ScoredPOICandidate(
        poi_id=poi_id,
        name=poi_id,
        logical_category=category,
        physical_table=f"poi_{category}",
        lat=lat,
        lng=lng,
        rating=4.5,
        final_poi_score=80,
    )


def test_route_planner_filters_adjacent_pois_under_one_km() -> None:
    constraints = FinalConstraints(
        hard_constraints=HardConstraints(required_slots=["activity", "restaurant"])
    )
    balanced = {
        "activity": [_poi("a", 39.9000, 116.4000, "activity")],
        "restaurant": [
            _poi("too_close", 39.9005, 116.4005, "restaurant"),
            _poi("ok", 39.9200, 116.4200, "restaurant"),
        ],
    }

    plans = create_route_plans(balanced, constraints)

    assert plans
    assert all(slot.poi_id != "too_close" for plan in plans for slot in plan.slots)
