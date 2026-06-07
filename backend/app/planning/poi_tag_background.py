from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


BACKGROUND_PATH = Path(__file__).with_name("poi_tag_background.json")


@lru_cache(maxsize=1)
def load_static_poi_tag_background() -> dict[str, Any]:
    """读取用户提供的 POI 标签背景知识。

    这份数据是从表级标签统计中整理出来的静态兜底：复合标签已经按 `| / & ,`
    等分隔符拆开并去重。数据库可用时它用于补齐 prompt 标签；数据库不可用时它
    作为 LLM 意图识别的主要标签白名单，避免模型凭空造标签。
    """

    if not BACKGROUND_PATH.exists():
        return {"tables": {}}
    try:
        data = json.loads(BACKGROUND_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tables": {}}
    return data if isinstance(data, dict) else {"tables": {}}


def static_tags_by_logical_category() -> dict[str, list[str]]:
    """按逻辑类别返回静态标签列表，保持 JSON 中的热度排序。"""

    data = load_static_poi_tag_background()
    result: dict[str, list[str]] = {}
    for info in (data.get("tables") or {}).values():
        if not isinstance(info, dict):
            continue
        logical = str(info.get("logical_category") or "").strip()
        if not logical:
            continue
        tags = []
        for item in info.get("tags") or []:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                tags.append(name)
        result[logical] = list(dict.fromkeys(tags))
    return result


def static_tag_fields_by_table() -> dict[str, list[str]]:
    """返回用户提供的每张物理表标签字段。"""

    data = load_static_poi_tag_background()
    result: dict[str, list[str]] = {}
    for table, info in (data.get("tables") or {}).items():
        if not isinstance(info, dict):
            continue
        fields = [str(field).strip() for field in info.get("tag_fields") or [] if str(field).strip()]
        if fields:
            result[str(table)] = list(dict.fromkeys(fields))
    return result
