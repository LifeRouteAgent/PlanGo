from __future__ import annotations

import json
import time
from typing import Any

from app.services.runtime_paths import MEMORY_DIR, ensure_runtime_dirs


class MemoryService:
    """文件型长期记忆服务。

    v1 只沉淀稳定偏好，不保存 API key、数据库密码、完整住址等敏感信息。
    Memory 是软约束，本轮用户明确输入的要求永远优先。
    """

    def __init__(self) -> None:
        ensure_runtime_dirs()
        self.memory_md = MEMORY_DIR / "MEMORY.md"
        self.profile_json = MEMORY_DIR / "user_profile.json"
        self.history_jsonl = MEMORY_DIR / "history.jsonl"
        if not self.memory_md.exists():
            self.memory_md.write_text("# LifeRoute Memory\n\n", encoding="utf-8")
        if not self.profile_json.exists():
            self.profile_json.write_text(
                json.dumps(_empty_profile(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def enrich_user_profile(self, user_profile: dict[str, Any] | None) -> dict[str, Any]:
        """把长期画像注入本轮 user_profile，供 Intent/Planner/Skill 当软约束使用。"""

        profile = dict(user_profile or {})
        memory_profile = self.read_profile()
        profile.setdefault("memory_profile", memory_profile)
        profile.setdefault("preferred_city", memory_profile.get("preferred_city"))
        profile.setdefault("preferred_areas", memory_profile.get("preferred_areas", []))
        profile.setdefault("indoor_preference", memory_profile.get("indoor_preference", False))
        profile.setdefault("disliked_keywords", memory_profile.get("disliked_keywords", []))
        profile.setdefault("favorite_categories", memory_profile.get("favorite_categories", {}))
        profile.setdefault("memory_snippets", self.search(str(profile.get("last_query", ""))))
        return profile

    def read_profile(self) -> dict[str, Any]:
        """读取用户画像 JSON，文件损坏时回退到空画像。"""

        try:
            data = json.loads(self.profile_json.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else _empty_profile()
        except (OSError, json.JSONDecodeError):
            return _empty_profile()

    def observe_user_query(self, query: str) -> None:
        """从用户自然语言里沉淀显式偏好。"""

        profile = self.read_profile()
        changed: list[str] = []
        disliked_keywords = profile.get("disliked_keywords", [])
        if not isinstance(disliked_keywords, list):
            disliked_keywords = []

        if any(word in query for word in ("不要室外", "别室外", "太热", "下雨", "室内")):
            profile["indoor_preference"] = True
            if "室外" not in disliked_keywords:
                disliked_keywords.append("室外")
            changed.append("偏好室内/避免室外")

        for marker in ("不要", "不想要", "别要"):
            if marker in query:
                term = query.split(marker, 1)[1].strip()[:12]
                if term and term not in disliked_keywords:
                    disliked_keywords.append(term)
                    changed.append(f"不喜欢 {term}")

        if "预算" in query and any(word in query for word in ("低", "省钱", "便宜", "200", "300")):
            profile["budget_level"] = "low"
            changed.append("偏好低预算")

        profile["disliked_keywords"] = disliked_keywords
        if changed:
            self._write_profile(profile)
            self._append_memory("用户偏好更新：" + "；".join(changed))
        self._append_history({"type": "user_query", "query": query})

    def observe_selected_plan(self, plan: dict[str, Any]) -> None:
        """用户采纳/执行方案后累计类别偏好和最近选择摘要。"""

        profile = self.read_profile()
        categories = profile.get("favorite_categories", {})
        if not isinstance(categories, dict):
            categories = {}
        for item in plan.get("items", []) if isinstance(plan.get("items"), list) else []:
            category = str(item.get("category") or "")
            if category:
                categories[category] = int(categories.get(category, 0) or 0) + 1
        profile["favorite_categories"] = categories
        profile["last_selected_plan_summary"] = {
            "id": plan.get("id"),
            "title": plan.get("title"),
            "estimated_budget": plan.get("estimated_budget"),
            "total_duration_minutes": plan.get("total_duration_minutes"),
        }
        self._write_profile(profile)
        self._append_memory(f"用户采纳方案：{plan.get('title') or plan.get('id')}")
        self._append_history({"type": "plan_selected", "plan": profile["last_selected_plan_summary"]})

    def search(self, query: str, *, limit: int = 5) -> list[str]:
        """关键词检索 MEMORY.md 和最近历史，不引入向量库。"""

        keywords = [token for token in query.replace("，", " ").replace(",", " ").split() if token]
        lines: list[str] = []
        if self.memory_md.exists():
            lines.extend(self.memory_md.read_text(encoding="utf-8").splitlines())
        if self.history_jsonl.exists():
            lines.extend(self.history_jsonl.read_text(encoding="utf-8").splitlines()[-80:])
        if not keywords:
            return [line for line in lines[-limit:] if line.strip()]
        matched = [
            line
            for line in lines
            if any(keyword in line for keyword in keywords) and line.strip()
        ]
        return matched[-limit:]

    def clear(self) -> None:
        """清空长期记忆和历史偏好。"""

        self.memory_md.write_text("# LifeRoute Memory\n\n", encoding="utf-8")
        self.profile_json.write_text(
            json.dumps(_empty_profile(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.history_jsonl.write_text("", encoding="utf-8")

    def _write_profile(self, profile: dict[str, Any]) -> None:
        self.profile_json.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _append_memory(self, line: str) -> None:
        with self.memory_md.open("a", encoding="utf-8") as file:
            file.write(f"- {time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")

    def _append_history(self, payload: dict[str, Any]) -> None:
        payload = {"timestamp": time.time(), **payload}
        with self.history_jsonl.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _empty_profile() -> dict[str, Any]:
    return {
        "preferred_city": "北京",
        "preferred_areas": [],
        "budget_level": "unknown",
        "indoor_preference": False,
        "favorite_categories": {},
        "disliked_keywords": [],
        "group_patterns": {},
        "last_selected_plan_summary": {},
    }
