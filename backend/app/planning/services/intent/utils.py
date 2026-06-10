from __future__ import annotations

import re

from app.planning.state import PHYSICAL_TABLES

LEGACY_TO_LOGICAL = {f"poi_{name}": name for name in PHYSICAL_TABLES}

SLOT_CATEGORIES = {
    "restaurant": ["restaurant"],
    "restaurant_2": ["restaurant"],
    "restaurant_or_cafe": ["restaurant"],
    "activity": ["activity", "attraction"],
    "attraction": ["attraction"],
    "activity_or_attraction": ["activity", "attraction"],
    "activity_or_entertainment": ["activity", "entertainment", "attraction"],
    "shopping": ["shopping"],
    "shopping_or_cafe": ["shopping", "restaurant"],
    "entertainment": ["entertainment"],
    "fitness": ["fitness"],
    "beauty": ["beauty"],
    "lifestyle": ["entertainment", "fitness", "beauty"],
    "beauty_or_spa": ["beauty"],
}

# fmt: off
MEAL_KEYWORDS = (
    "吃饭", "吃喝", "餐厅", "餐馆", "美食", "午饭", "午餐",
    "晚饭", "晚餐", "早饭", "早餐", "下午茶", "咖啡", "轻食",
    "火锅", "烧烤", "甜品",  "喝咖啡"
)
# fmt: on

INSPIRATION_MUST_PATTERN = re.compile(r"我想去\s*(?P<name>.+?)\s*[，,]\s*帮我搭配")

ORIGIN_TEXT_PATTERNS = (
    re.compile(r"(?:从|由)\s*(?P<name>[^，,。；;]{2,24})\s*(?:出发|开始|过去|去|到)"),
    re.compile(r"(?:我在|人在|当前位置在|现在在)\s*(?P<name>[^，,。；;]{2,24})"),
    re.compile(r"(?P<name>[^，,。；;]{2,24})\s*(?:附近|周边)\s*(?:出发|开始|安排|找|推荐)"),
)
