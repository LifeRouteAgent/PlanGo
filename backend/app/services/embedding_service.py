from __future__ import annotations

import hashlib
from typing import Any

from app.config import settings
from app.services.trace_recorder import record_trace_event


class EmbeddingService:
    """本地中文 embedding 服务。

    默认使用 BGE 中文模型；如果 sentence-transformers 或模型不可用，返回稳定的哈希向量，
    让向量记忆接口仍可测试、可降级，不阻塞主规划流程。
    """

    def __init__(
        self,
        *,
        model_path: str | None = None,
        dimension: int | None = None,
        allow_fallback: bool = True,
    ) -> None:
        self.model_path = model_path or settings.embedding_model_path
        self.dimension = int(dimension or settings.embedding_dimension)
        self.allow_fallback = allow_fallback
        self._model: Any | None = None
        self._load_error: str | None = None

    def embed_text(self, text: str) -> list[float]:
        """生成单条文本向量。"""

        vectors = self.embed_texts([text])
        return vectors[0] if vectors else self._fallback_vector(text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量，模型不可用时使用稳定 fallback。"""

        cleaned = [text.strip() for text in texts]
        if not cleaned:
            return []
        try:
            model = self._get_model()
            raw_vectors = model.encode(cleaned, normalize_embeddings=True)
            return [
                _resize_vector([float(value) for value in vector], self.dimension)
                for vector in raw_vectors
            ]
        except Exception as exc:  # noqa: BLE001 - embedding 是增强能力，失败必须可降级。
            self._load_error = str(exc)
            record_trace_event(
                "tool_call",
                {
                    "tool": "embedding.local_bge",
                    "success": False,
                    "error": str(exc),
                    "fallback": "hash_vector",
                },
            )
            if not self.allow_fallback:
                raise
            return [self._fallback_vector(text) for text in cleaned]

    @property
    def available(self) -> bool:
        """返回本地模型是否已经可用。"""

        try:
            self._get_model()
            return True
        except Exception:  # noqa: BLE001 - 只用于状态展示。
            return False

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def _get_model(self) -> Any:
        """延迟加载 sentence-transformers 模型。"""

        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            raise
        self._model = SentenceTransformer(self.model_path)
        return self._model

    def _fallback_vector(self, text: str) -> list[float]:
        """稳定哈希向量，仅用于 Milvus/模型不可用时的可测试降级。"""

        buckets = [0.0 for _ in range(self.dimension)]
        tokens = _tokenize(text)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            buckets[index] += sign
        norm = sum(value * value for value in buckets) ** 0.5 or 1.0
        return [round(value / norm, 6) for value in buckets]


def _resize_vector(vector: list[float], dimension: int) -> list[float]:
    """把模型输出维度对齐到 Milvus collection 维度。"""

    if len(vector) == dimension:
        return vector
    if len(vector) > dimension:
        return vector[:dimension]
    return [*vector, *([0.0] * (dimension - len(vector)))]


def _tokenize(text: str) -> list[str]:
    """轻量 tokenizer：中文按字，英文/数字按连续片段。"""

    tokens: list[str] = []
    current = ""
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            if current:
                tokens.append(current.lower())
                current = ""
            tokens.append(char)
        elif char.isalnum():
            current += char
        else:
            if current:
                tokens.append(current.lower())
                current = ""
    if current:
        tokens.append(current.lower())
    return tokens or [text]
