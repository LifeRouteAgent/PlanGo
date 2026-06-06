from __future__ import annotations

from typing import Any

from app.planning.state import LLMUnderstanding, SessionPreferenceProfile

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "restaurant": ("吃饭", "餐厅", "美食", "火锅", "烧烤", "咖啡", "甜品", "日料", "西餐"),
    "entertainment": ("KTV", "唱歌", "电影", "影院", "麻将", "棋牌", "桌游", "密室"),
    "activity": ("活动", "体验", "手作", "运动", "亲子", "展", "看展"),
    "attraction": ("景点", "公园", "散步", "环球", "游乐园"),
    "shopping": ("逛街", "购物", "商场", "买东西"),
    "fitness": ("健身", "运动", "羽毛球", "篮球", "瑜伽"),
    "beauty": ("按摩", "SPA", "美容", "美甲", "养生"),
}

DINING_KEYWORDS = (
    "火锅",
    "烧烤",
    "咖啡",
    "甜品",
    "日料",
    "西餐",
    "川菜",
    "粤菜",
    "清淡",
    "不辣",
)
ACTIVITY_KEYWORDS = (
    "KTV",
    "唱歌",
    "电影",
    "麻将",
    "棋牌",
    "桌游",
    "密室",
    "看展",
    "散步",
    "逛街",
    "按摩",
    "SPA",
    "羽毛球",
    "室内",
    "室外",
)
ROUTE_KEYWORDS = {
    "nearby": ("附近", "近一点", "别太远", "少走路", "路程短"),
    "low_movement": ("少折腾", "不要绕路", "轻松一点"),
    "public_transport": ("地铁", "公交", "公共交通"),
    "taxi": ("打车", "出租车", "网约车"),
}
NEGATIVE_MARKERS = ("不要", "不想", "别", "避开", "排除", "不喜欢", "不吃")
SENSITIVE_HINTS = ("手机号", "身份证", "住址", "地址", "公司", "学校", "收入", "疾病")


def extract_session_preference_profile(
    query: str,
    understanding: LLMUnderstanding | None,
) -> SessionPreferenceProfile:
    """Extract request-local preferences for immediate planning.

    This profile is intentionally synchronous and conservative: it only captures
    the current request's explicit planning needs and never writes long-term
    memory or sensitive inferred attributes.
    """

    text = query or ""
    preferred_categories = _dedupe([
        *_categories_from_understanding(understanding),
        *_categories_from_keywords(text),
    ])
    activity_preferences = _matched_keywords(text, ACTIVITY_KEYWORDS)
    dining_preferences = _matched_keywords(text, DINING_KEYWORDS)
    route_preferences = [
        label
        for label, keywords in ROUTE_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    negative_preferences = _negative_preferences(text)
    soft_preferences = _dedupe([
        *_safe_terms(activity_preferences),
        *_safe_terms(dining_preferences),
        *_safe_terms(_keywords_from_understanding(understanding)),
    ])
    hard_constraints = _hard_constraints_from_understanding(understanding)
    if route_preferences:
        hard_constraints["route_preferences"] = route_preferences

    scene_type = "unknown"
    companion_structure = "unknown"
    person_tags: list[str] = []
    if understanding:
        scene_type = understanding.scene.scene_type or "unknown"
        companion_structure = understanding.scene.party_type or "unknown"
        if understanding.scene.has_child:
            person_tags.append("child")
        if understanding.scene.people_count:
            hard_constraints["people_count"] = understanding.scene.people_count
    if "亲子" in text or "孩子" in text:
        person_tags.append("child")
    if "朋友" in text:
        person_tags.append("friends")
    if "情侣" in text or "对象" in text or "约会" in text:
        person_tags.append("couple")

    return SessionPreferenceProfile(
        scene_type=scene_type,
        companion_structure=companion_structure,
        person_tags=_dedupe(person_tags),
        activity_preferences=_safe_terms(activity_preferences),
        dining_preferences=_safe_terms(dining_preferences),
        route_preferences=route_preferences,
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
        negative_preferences=_safe_terms(negative_preferences),
        preferred_categories=preferred_categories,
        confidence=(
            0.82 if soft_preferences or preferred_categories or negative_preferences else 0.5
        ),
    )


def _categories_from_understanding(understanding: LLMUnderstanding | None) -> list[str]:
    if not understanding:
        return []
    return [
        str(category)
        for category in understanding.poi_recall_intent.target_logical_categories
        if category
    ]


def _keywords_from_understanding(understanding: LLMUnderstanding | None) -> list[str]:
    if not understanding:
        return []
    return [
        *understanding.poi_keyword_intent.preference_poi_keywords,
        *[
            tag.tag_name
            for tag in understanding.preference_tags_from_message.liked_tags
            if tag.tag_name
        ],
    ]


def _categories_from_keywords(text: str) -> list[str]:
    return [
        category
        for category, keywords in CATEGORY_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]


def _matched_keywords(text: str, candidates: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in candidates if keyword in text]


def _negative_preferences(text: str) -> list[str]:
    result: list[str] = []
    candidates = _dedupe([
        *(keyword for keywords in CATEGORY_KEYWORDS.values() for keyword in keywords),
        *DINING_KEYWORDS,
        *ACTIVITY_KEYWORDS,
    ])
    for keyword in candidates:
        index = text.find(keyword)
        if index < 0:
            continue
        prefix = text[max(0, index - 4) : index]
        if any(marker in prefix for marker in NEGATIVE_MARKERS):
            result.append(keyword)
            result.extend(
                category for category, keywords in CATEGORY_KEYWORDS.items() if keyword in keywords
            )
    return _dedupe(result)


def _hard_constraints_from_understanding(understanding: LLMUnderstanding | None) -> dict[str, Any]:
    if not understanding:
        return {}
    constraints: dict[str, Any] = {}
    if understanding.budget.total_budget is not None:
        constraints["total_budget"] = understanding.budget.total_budget
    if understanding.budget.budget_per_person is not None:
        constraints["budget_per_person"] = understanding.budget.budget_per_person
    if understanding.time.duration_hours is not None:
        constraints["duration_hours"] = understanding.time.duration_hours
    if understanding.distance.distance_preference != "unknown":
        constraints["distance_preference"] = understanding.distance.distance_preference
    return constraints


def _safe_terms(values: list[str]) -> list[str]:
    return [
        value
        for value in _dedupe(str(item).strip() for item in values if str(item).strip())
        if not any(hint in value for hint in SENSITIVE_HINTS)
    ][:16]


def _dedupe(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result
