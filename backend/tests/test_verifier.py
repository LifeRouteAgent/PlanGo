from __future__ import annotations

from app.graph.services import check_plan_availability
from app.graph.state import CandidatePlan, PlanSlot, ScoredPOICandidate


def test_availability_checker_filters_unavailable_plan() -> None:
    candidate = ScoredPOICandidate(
        poi_id="closed",
        name="closed",
        logical_category="activity",
        physical_table="poi_activities",
        raw_extra={"open_status": "closed"},
    )
    plan = CandidatePlan(
        plan_id="p1",
        generation_strategy="test",
        slots=[PlanSlot(slot_id="activity", poi_id="closed", poi_name="closed")],
    )

    availability, filtered, warnings = check_plan_availability([plan], {"activity": [candidate]})

    assert availability.by_poi["closed"].open_status == "closed"
    assert filtered == []
    assert warnings["p1"]
