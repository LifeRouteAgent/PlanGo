from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.trace_recorder import new_id, record_trace_event


@dataclass
class VectorMemoryRecord:
    """一条可写入 Milvus 的长期记忆。"""

    text: str
    user_id: str = "default"
    memory_type: str = "event"
    tags: list[str] = field(default_factory=list)
    category: str = ""
    source_event: str = "unknown"
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    memory_id: str = field(default_factory=lambda: new_id("mem"))
    timestamp: float = field(default_factory=time.time)


class VectorMemoryStore:
    """Milvus 向量记忆存储。

    该类永远不向上抛出 Milvus 连接异常；Milvus 不可用时返回空结果，让文件记忆兜底。
    """

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.embedding = embedding_service or EmbeddingService()
        self.enabled = settings.milvus_enabled
        self.dimension = settings.embedding_dimension
        self.memory_collection = settings.milvus_collection_memory
        self.profile_collection = settings.milvus_collection_user_profile
        self._client: Any | None = None
        self._last_error: str | None = None

    @property
    def available(self) -> bool:
        """Milvus 当前是否可用。"""

        if not self.enabled:
            return False
        return self._connect() is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def upsert_memory(self, record: VectorMemoryRecord) -> bool:
        """写入单条记忆向量。"""

        if not self.enabled:
            return False
        client = self._connect()
        if client is None:
            return False
        try:
            self._ensure_collection(self.memory_collection)
            vector = self.embedding.embed_text(record.text)
            client.upsert(
                collection_name=self.memory_collection,
                data=[self._record_to_row(record, vector)],
            )
            record_trace_event("tool_call", {
                "tool": "milvus.memory.upsert",
                "success": True,
                "memory_id": record.memory_id,
                "memory_type": record.memory_type,
            })
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_failure("milvus.memory.upsert", exc)
            return False

    def upsert_user_profile(self, user_id: str, profile_text: str, metadata: dict[str, Any]) -> bool:
        """写入用户画像向量，用于相似用户偏好检索和聚类。"""

        if not self.enabled:
            return False
        client = self._connect()
        if client is None:
            return False
        try:
            self._ensure_collection(self.profile_collection)
            record = VectorMemoryRecord(
                memory_id=f"profile_{user_id}",
                user_id=user_id,
                memory_type="user_profile",
                text=profile_text,
                tags=["profile"],
                category="profile",
                source_event="profile_update",
                metadata=metadata,
            )
            vector = self.embedding.embed_text(profile_text)
            client.upsert(
                collection_name=self.profile_collection,
                data=[self._record_to_row(record, vector)],
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_failure("milvus.profile.upsert", exc)
            return False

    def search_memory(self, query: str, *, limit: int = 5, user_id: str | None = None) -> list[dict[str, Any]]:
        """按语义检索长期记忆。"""

        return self._search(self.memory_collection, query, limit=limit, user_id=user_id)

    def search_similar_profiles(
        self,
        profile_text: str,
        *,
        limit: int = 5,
        exclude_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """检索相似用户画像。"""

        results = self._search(self.profile_collection, profile_text, limit=limit + 1)
        if exclude_user_id:
            results = [item for item in results if item.get("user_id") != exclude_user_id]
        return results[:limit]

    def profile_clusters(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """返回粗粒度画像聚类结果。

        v1 不引入复杂聚类依赖，按画像 metadata 中的高频偏好生成可解释分群。
        """

        client = self._connect()
        if client is None:
            return []
        try:
            rows = client.query(
                collection_name=self.profile_collection,
                filter="memory_type == 'user_profile'",
                output_fields=["user_id", "text", "tags", "category", "metadata"],
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            self._record_failure("milvus.profile.query", exc)
            return []
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            metadata = _json_loads(row.get("metadata"))
            key = _cluster_key(metadata)
            bucket = buckets.setdefault(key, {"cluster_id": key, "count": 0, "top_preferences": {}})
            bucket["count"] += 1
            for tag in metadata.get("memory_fit_tags", []) or metadata.get("disliked_keywords", []):
                bucket["top_preferences"][tag] = bucket["top_preferences"].get(tag, 0) + 1
        return [
            {
                **bucket,
                "cluster_label": _cluster_label(bucket["cluster_id"]),
                "top_preferences": sorted(
                    bucket["top_preferences"],
                    key=bucket["top_preferences"].get,
                    reverse=True,
                )[:8],
            }
            for bucket in buckets.values()
        ]

    def clear(self, *, user_id: str | None = None) -> None:
        """清空当前用户/session 的向量记忆。"""

        client = self._connect()
        if client is None:
            return
        expression = f'user_id == "{user_id}"' if user_id else ""
        for collection in (self.memory_collection, self.profile_collection):
            try:
                if expression:
                    client.delete(collection_name=collection, filter=expression)
                else:
                    client.drop_collection(collection)
            except Exception as exc:  # noqa: BLE001
                self._record_failure("milvus.clear", exc)

    def _search(
        self,
        collection: str,
        query: str,
        *,
        limit: int,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self._connect()
        if client is None or not query.strip():
            return []
        try:
            self._ensure_collection(collection)
            vector = self.embedding.embed_text(query)
            filter_expr = f'user_id == "{user_id}"' if user_id else ""
            raw = client.search(
                collection_name=collection,
                data=[vector],
                limit=limit,
                filter=filter_expr,
                output_fields=[
                    "memory_id",
                    "user_id",
                    "memory_type",
                    "text",
                    "tags",
                    "category",
                    "source_event",
                    "timestamp",
                    "weight",
                    "metadata",
                ],
            )
            hits = raw[0] if raw else []
            return [_hit_to_dict(hit) for hit in hits]
        except Exception as exc:  # noqa: BLE001
            self._record_failure("milvus.memory.search", exc)
            return []

    def _connect(self) -> Any | None:
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            from pymilvus import MilvusClient

            self._client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
            return self._client
        except Exception as exc:  # noqa: BLE001
            self._record_failure("milvus.connect", exc)
            return None

    def _ensure_collection(self, collection_name: str) -> None:
        client = self._connect()
        if client is None:
            return
        if client.has_collection(collection_name):
            return
        from pymilvus import DataType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("memory_id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dimension)
        schema.add_field("user_id", DataType.VARCHAR, max_length=128)
        schema.add_field("memory_type", DataType.VARCHAR, max_length=64)
        schema.add_field("text", DataType.VARCHAR, max_length=4096)
        schema.add_field("tags", DataType.VARCHAR, max_length=1024)
        schema.add_field("category", DataType.VARCHAR, max_length=128)
        schema.add_field("source_event", DataType.VARCHAR, max_length=128)
        schema.add_field("timestamp", DataType.DOUBLE)
        schema.add_field("weight", DataType.DOUBLE)
        schema.add_field("metadata", DataType.VARCHAR, max_length=4096)
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )

    def _record_to_row(self, record: VectorMemoryRecord, vector: list[float]) -> dict[str, Any]:
        return {
            "memory_id": record.memory_id,
            "embedding": vector,
            "user_id": record.user_id,
            "memory_type": record.memory_type,
            "text": record.text[:4000],
            "tags": json.dumps(record.tags, ensure_ascii=False),
            "category": record.category,
            "source_event": record.source_event,
            "timestamp": float(record.timestamp),
            "weight": float(record.weight),
            "metadata": json.dumps(record.metadata, ensure_ascii=False, default=str),
        }

    def _record_failure(self, tool: str, exc: Exception) -> None:
        self._last_error = str(exc)
        record_trace_event("tool_call", {
            "tool": tool,
            "success": False,
            "error": str(exc),
            "fallback": "file_memory",
        })


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    if isinstance(hit, dict):
        entity = hit.get("entity", {})
    else:
        entity = getattr(hit, "entity", None) or {}
    distance = getattr(hit, "distance", None)
    if distance is None and isinstance(hit, dict):
        distance = hit.get("distance") or hit.get("score")
    return {
        "memory_id": entity.get("memory_id"),
        "user_id": entity.get("user_id"),
        "memory_type": entity.get("memory_type"),
        "text": entity.get("text"),
        "tags": _json_loads(entity.get("tags")),
        "category": entity.get("category"),
        "source_event": entity.get("source_event"),
        "timestamp": entity.get("timestamp"),
        "weight": entity.get("weight"),
        "metadata": _json_loads(entity.get("metadata")),
        "score": distance,
    }


def _json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return {}
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {}


def _cluster_key(metadata: dict[str, Any]) -> str:
    budget = metadata.get("budget_level") or "unknown_budget"
    indoor = "indoor" if metadata.get("indoor_preference") else "mixed"
    favorite = metadata.get("favorite_categories", {})
    if isinstance(favorite, dict) and favorite:
        top_category = max(favorite, key=favorite.get)
    else:
        top_category = "general"
    return f"{indoor}_{budget}_{top_category}"


def _cluster_label(cluster_id: str) -> str:
    parts = cluster_id.split("_")
    labels = []
    if "indoor" in parts:
        labels.append("偏室内")
    if "low" in parts:
        labels.append("低预算")
    if parts:
        labels.append(parts[-1])
    return " / ".join(labels) if labels else cluster_id
