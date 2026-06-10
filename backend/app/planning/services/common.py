from __future__ import annotations

import re
from typing import Any

from app.planning.state import SafePOICandidate


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_dict_list(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _safe_float_value(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except TypeError, ValueError:
        return None


def _keyword_match(item: SafePOICandidate, keywords: list[str]) -> float:
    if not keywords:
        return 0.7
    text = " ".join(
        str(value or "")
        for value in [item.name, item.subcategory, item.address, " ".join(item.logic_tags)]
    ).lower()
    return sum(1 for keyword in keywords if str(keyword).lower() in text) / len(keywords)


def _clean_logic_tags(
    values: Any, category: str, subcategory: Any = None, limit: int = 6
) -> list[str]:
    result: list[str] = []
    candidates = list(values) if isinstance(values, list) else [values]
    if subcategory:
        candidates.insert(0, subcategory)
    for value in candidates:
        tag = _clean_tag_text(value)
        if not tag or tag in result:
            continue
        result.append(tag)
        if len(result) >= limit:
            break
    if not result:
        result.append(_category_label(category))
    return result


def _clean_tag_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if any(
        mark in text
        for mark in ("{", "}", "[", "]", "sub_category_id", "leaf_category_id", "category_id")
    ):
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ，,。；;：:|/\\")
    if text.lower() == "ktv":
        return "KTV"
    if any(mark in text for mark in (",", "，", ":", "：")):
        return ""
    if not text or len(text) > 15:
        return ""
    if text.lower() in {
        "activity",
        "attraction",
        "restaurant",
        "shopping",
        "entertainment",
        "fitness",
        "beauty",
        "mixed",
    }:
        return ""
    return text


def _category_label(category: str | None) -> str:
    return {
        "restaurant": "餐饮",
        "activity": "活动",
        "attraction": "景点",
        "shopping": "购物",
        "entertainment": "娱乐",
        "fitness": "运动",
        "beauty": "放松",
    }.get(str(category or ""), "本地生活")


def _image_list(images: Any, image_url: Any = None) -> list[str]:
    result: list[str] = []
    for value in [image_url, *(images if isinstance(images, list) else [images])]:
        if isinstance(value, dict):
            value = value.get("url") or value.get("src")
        text = str(value or "").strip().strip('"').strip("'")
        if text.startswith(("http://", "https://")) and text not in result:
            result.append(text)
    return result[:8]


def _first_image_value(image_url: Any, images: Any) -> str | None:
    values = _image_list(images, image_url)
    return values[0] if values else None


__all__ = [name for name in globals() if name.startswith("_") or name.isupper()]
