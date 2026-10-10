"""Local semantic embeddings and cosine-similarity search."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


class EmbeddingProvider(Protocol):
    model_name: str

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed indexed passages."""

    def embed_query(self, text: str) -> list[float]:
        """Embed one search query."""


class FastEmbedProvider:
    """CPU-friendly local embedding provider backed by FastEmbed/ONNX."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        cache_dir: str | Path | None = None,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as error:  # optional dependency
            raise RuntimeError(
                "Semantic embeddings need the optional 'semantic' extra: pip install \"supplier-integrity-desk[semantic]\""
            ) from error

        self.model_name = model_name
        selected_cache = Path(
            cache_dir or os.environ.get("SUPPLIER_DESK_MODEL_CACHE") or Path.home() / ".cache" / "supplier-integrity-desk" / "models"
        )
        selected_cache.mkdir(parents=True, exist_ok=True)
        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(selected_cache),
        )

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return list(self._model.query_embed([text]))[0].tolist()


@lru_cache(maxsize=1)
def get_default_embedding_provider() -> FastEmbedProvider:
    """Reuse one local ONNX model within a Python process."""
    return FastEmbedProvider()


class SemanticSearchIndex:
    """In-memory semantic index over stable record IDs and text."""

    def __init__(
        self,
        texts_by_id: dict[str, str],
        embedding_provider: EmbeddingProvider,
    ) -> None:
        if not texts_by_id:
            raise ValueError("At least one text is required.")
        self.model_name = embedding_provider.model_name
        self._provider = embedding_provider
        self._ids = list(texts_by_id)
        self._texts = {key: str(value) for key, value in texts_by_id.items()}
        vectors = embedding_provider.embed_passages([self._texts[key] for key in self._ids])
        self._vectors = self._normalize(np.asarray(vectors, dtype=float))

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return np.divide(
            vectors,
            norms,
            out=np.zeros_like(vectors),
            where=norms != 0,
        )

    def search(
        self,
        query_id: str,
        candidate_ids: set[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, float | str]]:
        if query_id not in self._texts:
            raise ValueError(f"Unknown semantic record ID: {query_id}")
        bounded_limit = max(1, min(int(limit), 25))
        query_vector = self._normalize(np.asarray(self._provider.embed_query(self._texts[query_id]), dtype=float))[0]
        scores = self._vectors @ query_vector
        allowed = candidate_ids if candidate_ids is not None else set(self._ids)
        results = [
            {
                "id": record_id,
                "similarity": round(float(max(-1.0, min(1.0, score))) * 100.0, 1),
            }
            for record_id, score in zip(self._ids, scores)
            if record_id != query_id and record_id in allowed
        ]
        results.sort(key=lambda item: (-float(item["similarity"]), str(item["id"])))
        return results[:bounded_limit]

    def search_text(
        self,
        query: str,
        candidate_ids: set[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, float | str]]:
        """Search indexed records with arbitrary query text."""
        bounded_limit = max(1, min(int(limit), 50))
        query_vector = self._normalize(np.asarray(self._provider.embed_query(query), dtype=float))[0]
        scores = self._vectors @ query_vector
        allowed = candidate_ids if candidate_ids is not None else set(self._ids)
        results = [
            {
                "id": record_id,
                "similarity": round(
                    float(max(-1.0, min(1.0, score))) * 100.0,
                    1,
                ),
            }
            for record_id, score in zip(self._ids, scores)
            if record_id in allowed
        ]
        results.sort(key=lambda item: (-float(item["similarity"]), str(item["id"])))
        return results[:bounded_limit]

    def similarity(self, left_id: str, right_id: str) -> float:
        """Return cosine similarity for two indexed IDs as a percentage."""
        if left_id not in self._texts or right_id not in self._texts:
            raise ValueError("Both IDs must exist in the semantic index.")
        result = self.search(left_id, candidate_ids={right_id}, limit=1)
        return float(result[0]["similarity"])
