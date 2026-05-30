from __future__ import annotations

from typing import Any


def semantic_types(constraints: dict[str, Any] | None) -> set[str]:
    """从 LLM 结构化理解结果中提取活动语义类型。

    这里是 Skill 层的主入口：推荐逻辑优先看 `activity_intents.semantic_type`，
    例如 `ktv`、`mahjong`、`massage`，而不是直接在用户原句里查关键词。
    """

    result: set[str] = set()
    for item in (constraints or {}).get("activity_intents", []) or []:
        if not isinstance(item, dict):
            continue
        semantic_type = str(item.get("semantic_type") or "").strip().lower()
        if semantic_type:
            result.add(semantic_type)
    return result


def semantic_keywords(constraints: dict[str, Any] | None) -> list[str]:
    """提取 LLM 给出的偏好关键词。

    `preference_keywords` 表示本轮明确偏好，`activity_intents[].keywords`
    表示某个槽位的语义词，二者合并后供 POI 标签/名称匹配使用。
    """

    constraints = constraints or {}
    keywords: list[str] = []
    keywords.extend(_as_string_list(constraints.get("preference_keywords")))
    for item in constraints.get("activity_intents", []) or []:
        if not isinstance(item, dict):
            continue
        keywords.extend(_as_string_list(item.get("keywords")))
        semantic_type = str(item.get("semantic_type") or "").strip()
        if semantic_type:
            keywords.append(semantic_type)
    return dedupe_strings(keywords)


def excluded_keywords(constraints: dict[str, Any] | None) -> list[str]:
    """提取用户本轮明确排斥的关键词。"""

    return dedupe_strings(_as_string_list((constraints or {}).get("excluded_keywords")))


def has_semantic_intent(constraints: dict[str, Any] | None) -> bool:
    """判断本轮是否已经有 LLM 语义结果。

    如果这里为 false，Skill 才允许使用旧的规则关键词 fallback。
    """

    constraints = constraints or {}
    return bool(
        constraints.get("activity_intents")
        or constraints.get("preference_keywords")
        or constraints.get("scene_requirements")
    )


def item_text(item: dict[str, Any]) -> str:
    """把 POI 的可匹配字段合成短文本。"""

    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    return " ".join(
        str(part)
        for part in [
            item.get("name"),
            item.get("category"),
            item.get("subcategory"),
            *tags,
        ]
        if part
    ).lower()


def item_matches_keywords(item: dict[str, Any], keywords: list[str]) -> bool:
    """判断 POI 是否命中任一语义关键词。"""

    text = item_text(item)
    return any(str(keyword).lower() in text for keyword in keywords if str(keyword).strip())


def dedupe_strings(values: list[str]) -> list[str]:
    """保持顺序的字符串去重。"""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _as_string_list(value: Any) -> list[str]:
    """把可能的列表字段规整成字符串列表。"""

    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
