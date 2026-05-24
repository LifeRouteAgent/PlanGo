from __future__ import annotations

import json
import time
from typing import Any

from app.services.runtime_paths import MEMORY_DIR, ensure_runtime_dirs
from app.services.vector_memory_store import VectorMemoryRecord, VectorMemoryStore


class MemoryService:
    """混合长期记忆服务。

    文件层用于可读审计和 fallback；Milvus 层用于语义检索、相似画像召回和画像聚类。
    记忆永远是软约束，本轮用户显式输入优先级最高。
    """

    def __init__(self, vector_store: VectorMemoryStore | None = None) -> None:
        ensure_runtime_dirs()
        self.memory_md = MEMORY_DIR / "MEMORY.md"
        self.profile_json = MEMORY_DIR / "user_profile.json"
        self.history_jsonl = MEMORY_DIR / "history.jsonl"
        self.vector_store = vector_store or VectorMemoryStore()
        if not self.memory_md.exists():
            self.memory_md.write_text("# LifeRoute Memory\n\n", encoding="utf-8")
        if not self.profile_json.exists():
            self.profile_json.write_text(
                json.dumps(_empty_profile(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def enrich_user_profile(self, user_profile: dict[str, Any] | None) -> dict[str, Any]:
        """把压缩后的长期画像注入本轮 user_profile。"""

        profile = dict(user_profile or {})
        user_id = _user_id(profile)
        memory_profile = self.read_profile()
        query = str(profile.get("last_query", ""))
        memory_context = self.build_memory_context(query=query, user_id=user_id)
        similar = self.similar_user_preference_search(memory_profile, user_id=user_id)
        profile.setdefault("memory_profile", memory_profile)
        profile.setdefault("memory_context", memory_context)
        profile.setdefault("memory_snippets", memory_context.get("snippets", []))
        profile.setdefault("similar_user_preferences", similar)
        profile.setdefault("profile_cluster", _profile_cluster(memory_profile))
        profile.setdefault("memory_fit_tags", memory_context.get("memory_fit_tags", []))
        profile.setdefault("preferred_city", memory_profile.get("preferred_city"))
        profile.setdefault("preferred_areas", memory_profile.get("preferred_areas", []))
        profile.setdefault("indoor_preference", memory_profile.get("indoor_preference", False))
        profile.setdefault("disliked_keywords", memory_profile.get("disliked_keywords", []))
        profile.setdefault("favorite_categories", memory_profile.get("favorite_categories", {}))
        return profile

    def build_memory_context(
        self, *, query: str, user_id: str = "default", limit: int = 5
    ) -> dict[str, Any]:
        """构建给上下文层使用的压缩记忆，只返回少量摘要。"""

        profile = self.read_profile()
        vector_hits = self.vector_store.search_memory(query, limit=limit, user_id=user_id)
        snippets = [str(hit.get("text", "")) for hit in vector_hits if hit.get("text")]
        if len(snippets) < limit:
            snippets.extend(self.search(query, limit=limit - len(snippets)))
        snippets = _dedupe(snippets)[:limit]
        memory_fit_tags = _memory_fit_tags(profile, snippets)
        return {
            "profile_summary": _profile_text(profile),
            "snippets": snippets,
            "memory_fit_tags": memory_fit_tags,
            "source": "milvus+file" if vector_hits else "file",
        }

    def read_profile(self) -> dict[str, Any]:
        """读取用户画像 JSON，文件损坏时回退为空画像。"""

        try:
            data = json.loads(self.profile_json.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else _empty_profile()
        except OSError, json.JSONDecodeError:
            return _empty_profile()

    def observe_user_query(self, query: str, *, user_id: str = "default") -> None:
        """从用户自然语言里沉淀显式偏好，并同步写入向量记忆。"""

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
            self._upsert_profile_vector(user_id, profile)
        self._append_history({"type": "user_query", "query": query})
        self.vector_store.upsert_memory(
            VectorMemoryRecord(
                user_id=user_id,
                memory_type="user_query",
                text=f"用户输入：{query}",
                tags=_extract_tags(query),
                category="query",
                source_event="user_query",
                metadata={"query": query, "profile_after": _safe_profile_metadata(profile)},
            )
        )

    def observe_selected_plan(self, plan: dict[str, Any], *, user_id: str = "default") -> None:
        """用户采纳/执行方案后累计类别偏好和最近选择摘要。"""

        profile = self.read_profile()
        categories = profile.get("favorite_categories", {})
        if not isinstance(categories, dict):
            categories = {}
        selected_tags: list[str] = []
        for item in plan.get("items", []) if isinstance(plan.get("items"), list) else []:
            category = str(item.get("category") or "")
            if category:
                categories[category] = int(categories.get(category, 0) or 0) + 1
            selected_tags.extend(str(tag) for tag in item.get("tags", [])[:3])
        profile["favorite_categories"] = categories
        profile["last_selected_plan_summary"] = {
            "id": plan.get("id"),
            "title": plan.get("title"),
            "estimated_budget": plan.get("estimated_budget"),
            "total_duration_minutes": plan.get("total_duration_minutes"),
        }
        self._write_profile(profile)
        self._append_memory(f"用户采纳方案：{plan.get('title') or plan.get('id')}")
        self._append_history(
            {"type": "plan_selected", "plan": profile["last_selected_plan_summary"]}
        )
        self._upsert_profile_vector(user_id, profile)
        self.vector_store.upsert_memory(
            VectorMemoryRecord(
                user_id=user_id,
                memory_type="plan_selected",
                text=_plan_memory_text(plan),
                tags=_dedupe(selected_tags),
                category="plan",
                source_event="plan_selected",
                weight=1.4,
                metadata={"plan": profile["last_selected_plan_summary"]},
            )
        )

    def search(self, query: str, *, limit: int = 5) -> list[str]:
        """关键词检索 MEMORY.md 和最近历史，不依赖向量库。"""

        keywords = [token for token in query.replace("，", " ").replace(",", " ").split() if token]
        lines: list[str] = []
        if self.memory_md.exists():
            lines.extend(self.memory_md.read_text(encoding="utf-8").splitlines())
        if self.history_jsonl.exists():
            lines.extend(self.history_jsonl.read_text(encoding="utf-8").splitlines()[-80:])
        if not keywords:
            return [line for line in lines[-limit:] if line.strip()]
        matched = [
            line for line in lines if any(keyword in line for keyword in keywords) and line.strip()
        ]
        return matched[-limit:]

    def semantic_search(
        self, query: str, *, limit: int = 5, user_id: str = "default"
    ) -> list[dict[str, Any]]:
        """语义检索长期记忆，Milvus 不可用时返回文件检索结果。"""

        vector_hits = self.vector_store.search_memory(query, limit=limit, user_id=user_id)
        if vector_hits:
            return vector_hits
        return [
            {"text": line, "source": "file", "score": None}
            for line in self.search(query, limit=limit)
        ]

    def similar_user_preference_search(
        self,
        profile: dict[str, Any] | None = None,
        *,
        user_id: str = "default",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """检索相似用户画像，返回可作为召回软约束的偏好摘要。"""

        profile_data = profile or self.read_profile()
        hits = self.vector_store.search_similar_profiles(
            _profile_text(profile_data),
            limit=limit,
            exclude_user_id=user_id,
        )
        return [
            {
                "user_id": hit.get("user_id"),
                "summary": hit.get("text"),
                "metadata": hit.get("metadata", {}),
                "score": hit.get("score"),
            }
            for hit in hits
        ]

    def rebuild_vector_index(self, *, user_id: str = "default") -> dict[str, Any]:
        """把文件记忆重建到 Milvus。"""

        profile = self.read_profile()
        count = 0
        for line in self.search("", limit=200):
            if self.vector_store.upsert_memory(
                VectorMemoryRecord(
                    user_id=user_id,
                    memory_type="rebuild",
                    text=line,
                    tags=_extract_tags(line),
                    category="history",
                    source_event="rebuild_index",
                )
            ):
                count += 1
        profile_ok = self._upsert_profile_vector(user_id, profile)
        return {
            "ok": True,
            "memory_vectors": count,
            "profile_vector": profile_ok,
            "milvus_available": self.vector_store.available,
            "fallback_reason": self.vector_store.last_error,
        }

    def clusters(self) -> list[dict[str, Any]]:
        """返回向量画像的粗粒度聚类结果。"""

        return self.vector_store.profile_clusters()

    def profile_payload(self, *, user_id: str = "default") -> dict[str, Any]:
        """返回前端/调试接口可展示的画像和向量状态。"""

        profile = self.read_profile()
        return {
            "profile": profile,
            "memory_context": self.build_memory_context(query="", user_id=user_id),
            "similar_user_preferences": self.similar_user_preference_search(
                profile, user_id=user_id
            ),
            "profile_cluster": _profile_cluster(profile),
            "vector_store": {
                "enabled": self.vector_store.enabled,
                "available": self.vector_store.available,
                "last_error": self.vector_store.last_error,
            },
        }

    def clear(self, *, user_id: str | None = None) -> None:
        """清空长期记忆和向量记忆。"""

        self.memory_md.write_text("# LifeRoute Memory\n\n", encoding="utf-8")
        self.profile_json.write_text(
            json.dumps(_empty_profile(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.history_jsonl.write_text("", encoding="utf-8")
        self.vector_store.clear(user_id=user_id)

    def _upsert_profile_vector(self, user_id: str, profile: dict[str, Any]) -> bool:
        return self.vector_store.upsert_user_profile(
            user_id=user_id,
            profile_text=_profile_text(profile),
            metadata={
                **_safe_profile_metadata(profile),
                "memory_fit_tags": _memory_fit_tags(profile, []),
            },
        )

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


def _user_id(profile: dict[str, Any]) -> str:
    return str(profile.get("user_id") or profile.get("session_id") or "default")


def _safe_profile_metadata(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "preferred_city": profile.get("preferred_city"),
        "preferred_areas": profile.get("preferred_areas", []),
        "budget_level": profile.get("budget_level"),
        "indoor_preference": profile.get("indoor_preference", False),
        "favorite_categories": profile.get("favorite_categories", {}),
        "disliked_keywords": profile.get("disliked_keywords", []),
    }


def _profile_text(profile: dict[str, Any]) -> str:
    favorite_categories = profile.get("favorite_categories", {})
    top_categories = []
    if isinstance(favorite_categories, dict):
        top_categories = sorted(favorite_categories, key=favorite_categories.get, reverse=True)[:5]
    return "；".join([
        f"城市：{profile.get('preferred_city', '北京')}",
        f"常去区域：{'、'.join(profile.get('preferred_areas', []) or []) or '未知'}",
        f"预算等级：{profile.get('budget_level', 'unknown')}",
        f"偏好室内：{bool(profile.get('indoor_preference', False))}",
        f"喜欢类别：{'、'.join(top_categories) or '未知'}",
        f"不喜欢：{'、'.join(profile.get('disliked_keywords', []) or []) or '无'}",
    ])


def _profile_cluster(profile: dict[str, Any]) -> dict[str, Any]:
    budget = profile.get("budget_level", "unknown")
    indoor = "indoor" if profile.get("indoor_preference") else "mixed"
    favorite_categories = profile.get("favorite_categories", {})
    top_category = "general"
    if isinstance(favorite_categories, dict) and favorite_categories:
        top_category = max(favorite_categories, key=favorite_categories.get)
    cluster_id = f"{indoor}_{budget}_{top_category}"
    return {
        "cluster_id": cluster_id,
        "cluster_label": " / ".join(
            item
            for item in [
                "偏室内" if indoor == "indoor" else "室内外均可",
                "低预算" if budget == "low" else "预算未知",
                top_category,
            ]
            if item
        ),
    }


def _memory_fit_tags(profile: dict[str, Any], snippets: list[str]) -> list[str]:
    tags: list[str] = []
    if profile.get("indoor_preference"):
        tags.append("室内")
    if profile.get("budget_level") == "low":
        tags.append("低预算")
    tags.extend(str(item) for item in profile.get("disliked_keywords", [])[:5])
    for snippet in snippets:
        tags.extend(_extract_tags(snippet))
    return _dedupe(tags)[:12]


def _extract_tags(text: str) -> list[str]:
    candidates = [
        "室内",
        "室外",
        "低预算",
        "省钱",
        "KTV",
        "麻将",
        "唱歌",
        "亲子",
        "朋友",
        "情侣",
        "火锅",
        "按摩",
    ]
    return [tag for tag in candidates if tag.lower() in text.lower()]


def _plan_memory_text(plan: dict[str, Any]) -> str:
    items = plan.get("items", []) if isinstance(plan.get("items"), list) else []
    names = "、".join(str(item.get("name", "")) for item in items[:5])
    categories = "、".join(str(item.get("category", "")) for item in items[:5])
    return (
        f"用户采纳方案：{plan.get('title') or plan.get('id')}；"
        f"地点：{names}；类别：{categories}；"
        f"预算：{plan.get('estimated_budget')}；时长：{plan.get('total_duration_minutes')}"
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result
