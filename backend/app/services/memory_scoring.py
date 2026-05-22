from __future__ import annotations

from typing import Any


def memory_score_adjustment(item: dict[str, Any], user_profile: dict[str, Any] | None) -> float:
    """根据长期画像给 POI 轻量加权。

    本轮显式约束仍在 Collector/Skill 中优先生效；这里只做软加权，避免 Memory 绑架结果。
    """

    profile = user_profile or {}
    memory_profile = profile.get("memory_profile", {}) if isinstance(profile.get("memory_profile"), dict) else {}
    favorite_categories = memory_profile.get("favorite_categories", {})
    disliked_keywords = set(str(v) for v in profile.get("disliked_keywords", []) or [])
    memory_tags = set(str(v) for v in profile.get("memory_fit_tags", []) or [])
    item_text = _item_text(item)
    score = 0.0
    if isinstance(favorite_categories, dict):
        score += min(0.35, int(favorite_categories.get(str(item.get("category")), 0) or 0) * 0.05)
    if profile.get("indoor_preference") and any(tag in item_text for tag in ("室内", "商场", "KTV", "影院", "桌游", "棋牌")):
        score += 0.18
    if profile.get("budget_level") == "low" and str(item.get("price_level")) == "low":
        score += 0.12
    if any(tag and tag in item_text for tag in memory_tags):
        score += 0.08
    if any(keyword and keyword in item_text for keyword in disliked_keywords):
        score -= 0.8
    return round(max(-1.0, min(0.8, score)), 3)


def attach_memory_fields(item: dict[str, Any], user_profile: dict[str, Any] | None) -> dict[str, Any]:
    """把 memory 加权结果写回推荐项，方便 Ranker 和前端解释。"""

    adjustment = memory_score_adjustment(item, user_profile)
    tags = _matched_memory_tags(item, user_profile or {})
    return {
        **item,
        "memory_score_adjustment": adjustment,
        "memory_fit_tags": tags,
        "score": round(float(item.get("score", 0) or 0) + adjustment, 2),
    }


def plan_memory_fit(plan: dict[str, Any], user_profile: dict[str, Any] | None) -> float:
    """计算整条方案与长期偏好的匹配度，返回 0-1。"""

    items = plan.get("items", []) if isinstance(plan.get("items"), list) else []
    if not items:
        return 0.5
    adjustments = [memory_score_adjustment(item, user_profile) for item in items]
    normalized = 0.5 + sum(adjustments) / max(1, len(adjustments))
    return round(max(0.0, min(1.0, normalized)), 3)


def _matched_memory_tags(item: dict[str, Any], user_profile: dict[str, Any]) -> list[str]:
    text = _item_text(item)
    tags = []
    for tag in user_profile.get("memory_fit_tags", []) or []:
        if str(tag) in text:
            tags.append(str(tag))
    if user_profile.get("indoor_preference") and any(word in text for word in ("室内", "商场", "KTV", "影院")):
        tags.append("室内偏好")
    return list(dict.fromkeys(tags))[:5]


def _item_text(item: dict[str, Any]) -> str:
    return " ".join([
        str(item.get("name", "")),
        str(item.get("category", "")),
        str(item.get("subcategory", "")),
        str(item.get("address", "")),
        " ".join(str(tag) for tag in item.get("tags", []) or []),
    ])
