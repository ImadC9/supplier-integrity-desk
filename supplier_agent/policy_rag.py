"""Local, citation-preserving policy retrieval.

LlamaIndex supplies keyword retrieval; optional embeddings add vectors.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from llama_index.core import Document, SimpleKeywordTableIndex
from llama_index.core.llms import MockLLM

from .semantic import (
    EmbeddingProvider,
    SemanticSearchIndex,
    get_default_embedding_provider,
)

_TITLE = re.compile(r"^#\s+(.+)$")
_SECTION = re.compile(r"^##\s+(.+)$")
_WORD = re.compile(r"[a-z0-9]+")


def _load_policy_sections(policy_dir: Path) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(policy_dir.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        title = ""
        section = ""
        body: list[str] = []

        def add_section() -> None:
            text = "\n".join(body).strip()
            if not title or not section or not text:
                return
            node_id = f"{path.stem}:{section}"
            documents.append(
                Document(
                    text=f"{title}\n{section}\n{text}",
                    metadata={
                        "document": title,
                        "section": section,
                        "source_file": path.name,
                        "node_id": node_id,
                    },
                    id_=node_id,
                )
            )

        for line in lines:
            title_match = _TITLE.match(line)
            section_match = _SECTION.match(line)
            if title_match:
                title = title_match.group(1).strip()
            elif section_match:
                add_section()
                section = section_match.group(1).strip()
                body = []
            elif section:
                body.append(line)
        add_section()
    return documents


class PolicyRetriever:
    """Retrieve bounded policy passages from an approved local directory."""

    def __init__(
        self,
        policy_dir: str | Path,
        embedding_provider: EmbeddingProvider | None = None,
        semantic_enabled: bool = True,
    ) -> None:
        self.policy_dir = Path(policy_dir)
        documents = _load_policy_sections(self.policy_dir)
        if not documents:
            raise ValueError(f"No policy sections found in {self.policy_dir}")
        self._index = SimpleKeywordTableIndex.from_documents(
            documents,
            llm=MockLLM(),
        )
        self._documents_by_id = {str(document.metadata["node_id"]): document for document in documents}
        self._semantic_index = None
        if semantic_enabled:
            provider = embedding_provider or get_default_embedding_provider()
            self._semantic_index = SemanticSearchIndex(
                {node_id: document.text for node_id, document in self._documents_by_id.items()},
                provider,
            )

    def retrieve(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 10))
        retriever = self._index.as_retriever(
            num_chunks_per_query=50,
        )
        keyword_nodes = retriever.retrieve(query)
        keyword_ids = {str(item.node.metadata["node_id"]) for item in keyword_nodes}
        semantic_results = (
            self._semantic_index.search_text(
                query,
                limit=50,
            )
            if self._semantic_index is not None
            else []
        )
        semantic_by_id = {str(item["id"]): float(item["similarity"]) for item in semantic_results}
        query_terms = set(_WORD.findall(query.casefold()))
        keyword_scores = {}
        for node_id in keyword_ids:
            document_terms = set(_WORD.findall(self._documents_by_id[node_id].text.casefold()))
            keyword_scores[node_id] = len(query_terms & document_terms) / len(query_terms) if query_terms else 0.0
        candidate_ids = keyword_ids | set(semantic_by_id)
        ranked_ids = sorted(
            candidate_ids,
            key=lambda node_id: (
                -0.4 * keyword_scores.get(node_id, 0.0) - 0.6 * semantic_by_id.get(node_id, 0.0) / 100.0,
                node_id,
            ),
        )
        results: list[dict[str, Any]] = []
        for node_id in ranked_ids[:bounded_limit]:
            document_node = self._documents_by_id[node_id]
            metadata = document_node.metadata
            document = str(metadata["document"])
            section = str(metadata["section"])
            text = document_node.text
            prefix = f"{document}\n{section}\n"
            if text.startswith(prefix):
                text = text[len(prefix) :]
            results.append(
                {
                    "document": document,
                    "section": section,
                    "text": text.strip(),
                    "citation": f"{document} § {section}",
                    "source_file": str(metadata["source_file"]),
                    "retrieval_mode": "HYBRID_KEYWORD_VECTOR" if self._semantic_index else "KEYWORD",
                    "semantic_similarity": semantic_by_id.get(node_id, 0.0),
                    "embedding_model": self._semantic_index.model_name if self._semantic_index else None,
                }
            )
        return results
