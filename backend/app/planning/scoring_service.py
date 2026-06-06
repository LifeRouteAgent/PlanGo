from __future__ import annotations

from dataclasses import dataclass

from app.planning.state import (
    FinalConstraints,
    POIScoreBreakdown,
    SafePOICandidate,
    ScoredPOICandidate,
)


@dataclass(frozen=True)
class POIScoreWeights:
    """POI 打分权重。

    当前先保持 V2 既有排序行为：距离、标签、关键词各占主要权重，质量作为兜底；
    memory 继续作为小额加分，风险项作为扣分。后续如果要改权重，应从配置注入。
    """

    distance: float = 0.30
    tag: float = 0.30
    keyword: float = 0.30
    quality: float = 0.10
    memory_bonus: float = 5.0
    risk_penalty: float = 100.0


DEFAULT_POI_SCORE_WEIGHTS = POIScoreWeights()


def score_candidates(
    raw: dict[str, list[SafePOICandidate]],
    constraints: FinalConstraints,
    memory_tags: list[str],
    *,
    weights: POIScoreWeights = DEFAULT_POI_SCORE_WEIGHTS,
) -> dict[str, list[ScoredPOICandidate]]:
    """按 slot 对候选 POI 打分。

    Collector 只负责召回候选；这里负责把候选转成 `ScoredPOICandidate`，
    并保留 score_breakdown/reasons/warnings，方便后续解释和测试。
    """

    result: dict[str, list[ScoredPOICandidate]] = {}
    preference_keywords = constraints.soft_preferences.preference_keywords
    liked_tags = constraints.soft_preferences.liked_logic_tags
    floor = constraints.rating_policy.min_rating_floor
    for slot, items in raw.items():
        scored: list[ScoredPOICandidate] = []
        for item in items:
            if not item.must_include and item.rating is not None and item.rating < floor:
                continue
            scored.append(
                score_one_candidate(
                    item,
                    constraints,
                    preference_keywords=preference_keywords,
                    liked_tags=liked_tags,
                    memory_tags=memory_tags,
                    weights=weights,
                )
            )
        result[slot] = sorted(scored, key=lambda item: item.final_poi_score, reverse=True)
    return result


def score_one_candidate(
    item: SafePOICandidate,
    constraints: FinalConstraints,
    *,
    preference_keywords: list[str],
    liked_tags: list[str],
    memory_tags: list[str],
    weights: POIScoreWeights = DEFAULT_POI_SCORE_WEIGHTS,
) -> ScoredPOICandidate:
    quality = quality_score(item.rating)
    distance = distance_score(item.distance_km, constraints.distance_policy.max_radius_km)
    budget = budget_score(item.avg_price, constraints.budget_policy.soft_upper_per_person)
    logic = tag_score(item.logic_tags, liked_tags)
    keyword = keyword_score(item, preference_keywords)
    memory = memory_score(item.logic_tags, memory_tags)
    risk = risk_penalty(item)
    final = final_score(
        distance_score_value=distance,
        tag_score_value=logic,
        keyword_score_value=keyword,
        quality_score_value=quality,
        memory_score_value=memory,
        risk_penalty_value=risk,
        weights=weights,
    )
    return ScoredPOICandidate(
        **item.model_dump(),
        final_poi_score=round(final, 2),
        score_breakdown=POIScoreBreakdown(
            quality_score=quality,
            distance_score=distance,
            budget_score=budget,
            scene_score=keyword,
            keyword_match_score=keyword,
            logic_tag_match_score=logic,
            memory_score=memory,
            risk_penalty=risk,
        ),
        reasons=score_reasons(distance=distance, logic=logic, keyword=keyword, memory=memory),
        warnings=["价格未知"] if item.avg_price is None else [],
    )


def final_score(
    *,
    distance_score_value: float,
    tag_score_value: float,
    keyword_score_value: float,
    quality_score_value: float,
    memory_score_value: float,
    risk_penalty_value: float,
    weights: POIScoreWeights = DEFAULT_POI_SCORE_WEIGHTS,
) -> float:
    return (
        100
        * (
            weights.distance * distance_score_value
            + weights.tag * tag_score_value
            + weights.keyword * keyword_score_value
            + weights.quality * quality_score_value
        )
        + memory_score_value * weights.memory_bonus
        - risk_penalty_value * weights.risk_penalty
    )


def quality_score(rating: float | None) -> float:
    return min(1, (rating or 4.0) / 5)


def distance_score(distance_km: float | None, max_radius_km: float | None) -> float:
    if distance_km is None:
        return 0.65
    return max(0, 1 - distance_km / max(1, max_radius_km or 1))


def budget_score(price: float | None, soft_upper: float | None) -> float:
    if price is None or soft_upper is None:
        return 0.65
    return 1.0 if price <= soft_upper else max(0, 1 - (price - soft_upper) / max(1, soft_upper))


def tag_score(tags: list[str], desired: list[str]) -> float:
    if not desired:
        return 0.7
    text = " ".join(tags)
    return sum(1 for tag in desired if tag in text) / len(desired)


def keyword_score(item: SafePOICandidate, keywords: list[str]) -> float:
    if not keywords:
        return 0.7
    text = " ".join(
        str(value or "")
        for value in [item.name, item.subcategory, item.address, " ".join(item.logic_tags)]
    ).lower()
    return sum(1 for keyword in keywords if str(keyword).lower() in text) / len(keywords)


def memory_score(tags: list[str], memory_tags: list[str]) -> float:
    return tag_score(tags, memory_tags)


def risk_penalty(item: SafePOICandidate) -> float:
    return (0.08 if item.avg_price is None else 0) + (
        0.06 if item.lat is None or item.lng is None else 0
    )


def score_reasons(*, distance: float, logic: float, keyword: float, memory: float) -> list[str]:
    reasons: list[str] = []
    if distance >= 0.7:
        reasons.append("距离匹配")
    if logic >= 0.7:
        reasons.append("标签匹配")
    if keyword >= 0.7:
        reasons.append("关键词匹配")
    if memory > 0:
        reasons.append("匹配历史偏好")
    return reasons or ["综合评分、距离和预算适配"]
