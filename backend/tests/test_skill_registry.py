from __future__ import annotations

from app.planning.graph_builder import build_planning_graph_v2


def test_v2_graph_can_be_built_without_legacy_skill_nodes() -> None:
    graph = build_planning_graph_v2()

    assert graph is not None
