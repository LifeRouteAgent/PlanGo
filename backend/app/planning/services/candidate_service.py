from __future__ import annotations

from app.planning.services.common import *


def score_candidates(
    raw: dict[str, list[SafePOICandidate]], constraints: FinalConstraints, memory_tags: list[str]
) -> dict[str, list[ScoredPOICandidate]]:
    # Graph 层保留旧函数名作为兼容入口，真实 POI 打分逻辑下沉到 scoring_service。
    return score_poi_candidates(raw, constraints, memory_tags)


def balance_candidates(
    scored: dict[str, list[ScoredPOICandidate]],
) -> dict[str, list[ScoredPOICandidate]]:
    result: dict[str, list[ScoredPOICandidate]] = {}
    slot_count = max(1, len(scored))
    keep_limit = _balanced_keep_limit(slot_count)
    for slot, items in scored.items():
        must = [item for item in items if item.must_include]
        selected: list[ScoredPOICandidate] = list(must)
        seen: dict[tuple[str, str, str, str], int] = {}
        for item in items:
            band = (
                "near"
                if (item.distance_km or 0) <= 3
                else "mid" if (item.distance_km or 0) <= 8 else "far"
            )
            key = (
                item.logical_category,
                item.subcategory or item.logical_category,
                _price_band(item.avg_price),
                band,
            )
            if item in selected:
                continue
            if seen.get(key, 0) >= 4 and len(selected) < keep_limit * 0.75:
                continue
            selected.append(item)
            seen[key] = seen.get(key, 0) + 1
            if len(selected) >= keep_limit:
                break
        if len(selected) < keep_limit:
            selected_ids = {item.poi_id for item in selected}
            for item in items:
                if item.poi_id not in selected_ids:
                    selected.append(item)
                    selected_ids.add(item.poi_id)
                if len(selected) >= keep_limit:
                    break
        result[slot] = selected
    return result


def _balanced_keep_limit(slot_count: int) -> int:
    if slot_count <= 1:
        return 150
    if slot_count == 2:
        return 80
    return 100


def _price_band(price: float | None) -> str:
    if price is None or price <= 0:
        return "unknown"
    if price < 80:
        return "low"
    if price < 200:
        return "mid"
    return "high"
