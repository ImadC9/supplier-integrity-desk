"""Controlled, read-only supplier data tools.

The public methods accept supplier IDs rather than raw identifiers or query
text. This keeps data access bounded and makes the future Excel-to-SQL or
Power-BI migration an implementation detail.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
from langchain_core.tools import tool
from rapidfuzz import fuzz, process

from .detector import DetectionConfig, DuplicateDetector
from .io import load_supplier_master, validate_supplier_master
from .profile import absent_fields
from .quality import QualityConfig, check_quality
from .semantic import (
    EmbeddingProvider,
    SemanticSearchIndex,
    get_default_embedding_provider,
)

AGENT_SAFE_SUPPLIER_FIELDS = [
    "SUPPLIER_ID",
    "SUPPLIER_NAME",
    "COMPANY",
    "SITE",
    "COUNTRY_CODE",
    "ACTIVE_STATUS",
    "SUPPLIER_CATEGORY",
    "PURCHASE_GROUP",
]

SEMANTIC_CANDIDATE_THRESHOLD = 85.0


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


class SupplierDataService:
    """Approved read-only operations over one supplier data source."""

    def __init__(
        self,
        workbook_path: str | pd.DataFrame,
        embedding_provider: EmbeddingProvider | None = None,
        semantic_enabled: bool = True,
        detection_config: DetectionConfig | None = None,
    ) -> None:
        self.workbook_path = workbook_path
        self.detector = DuplicateDetector(detection_config)
        self.suppliers = (
            validate_supplier_master(workbook_path) if isinstance(workbook_path, pd.DataFrame) else load_supplier_master(workbook_path)
        )
        self.prepared = self.detector.prepare(self.suppliers)
        self._embedding_provider = embedding_provider
        self.semantic_enabled = semantic_enabled
        self.quality_findings = check_quality(self.suppliers, QualityConfig(absent_fields=absent_fields(self.suppliers)))
        self._semantic_index: SemanticSearchIndex | None = None
        self._audit_log: list[dict[str, Any]] = []

    @staticmethod
    def _supplier_id(value: str) -> str:
        supplier_id = str(value).strip().upper()
        if not supplier_id:
            raise ValueError("supplier_id is required.")
        return supplier_id

    def _audit(self, tool_name: str, supplier_id: str, result_count: int) -> None:
        self._audit_log.append(
            {
                "tool": tool_name,
                "supplier_id": supplier_id,
                "result_count": result_count,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
        )

    def audit_snapshot(self) -> list[dict[str, Any]]:
        return [event.copy() for event in self._audit_log]

    def _target(self, supplier_id: str) -> pd.Series | None:
        normalized = self._supplier_id(supplier_id)
        match = self.prepared[self.prepared["SUPPLIER_ID"].astype(str).str.upper() == normalized]
        return None if match.empty else match.iloc[0]

    @staticmethod
    def _summary(row: pd.Series) -> dict[str, Any]:
        allowed = [
            "SUPPLIER_ID",
            "SUPPLIER_NAME",
            "COMPANY",
            "SITE",
            "COUNTRY_CODE",
            "ACTIVE_STATUS",
        ]
        return {field: _json_value(row.get(field)) for field in allowed}

    def get_supplier(self, supplier_id: str) -> dict[str, Any] | None:
        normalized = self._supplier_id(supplier_id)
        row = self._target(normalized)
        result = None if row is None else {str(key): _json_value(value) for key, value in row.items() if not str(key).startswith("_")}
        self._audit("get_supplier", normalized, int(result is not None))
        return result

    def _find_same(
        self,
        supplier_id: str,
        value_field: str,
        scope_field: str,
        tool_name: str,
    ) -> list[dict[str, Any]]:
        normalized = self._supplier_id(supplier_id)
        target = self._target(normalized)
        if target is None or not target[value_field] or (not target[scope_field] and self.detector.config.require_country):
            self._audit(tool_name, normalized, 0)
            return []
        matches = self.prepared[
            self.prepared[value_field].eq(target[value_field])
            & self.prepared[scope_field].eq(target[scope_field])
            & self.prepared["SUPPLIER_ID"].astype(str).str.upper().ne(normalized)
        ]
        results = [self._summary(row) for _, row in matches.iterrows()]
        self._audit(tool_name, normalized, len(results))
        return results

    def find_by_tax_id(self, supplier_id: str) -> list[dict[str, Any]]:
        return self._find_same(
            supplier_id,
            "_TAX_ID",
            "_COUNTRY",
            "find_by_tax_id",
        )

    def find_by_association_no(self, supplier_id: str) -> list[dict[str, Any]]:
        return self._find_same(
            supplier_id,
            "_ASSOCIATION_NO",
            "_COUNTRY",
            "find_by_association_no",
        )

    def find_by_bank_account(self, supplier_id: str) -> list[dict[str, Any]]:
        return self._find_same(
            supplier_id,
            "_BANK_ACCOUNT",
            "_BANK_COUNTRY",
            "find_by_bank_account",
        )

    def _find_same_contact(self, supplier_id: str, value_field: str, tool_name: str) -> list[dict[str, Any]]:
        normalized = self._supplier_id(supplier_id)
        target = self._target(normalized)
        if target is None or not target[value_field]:
            self._audit(tool_name, normalized, 0)
            return []
        matches = self.prepared[
            self.prepared[value_field].eq(target[value_field]) & self.prepared["SUPPLIER_ID"].astype(str).str.upper().ne(normalized)
        ]
        if len(matches) >= self.detector.config.max_shared_identifier_group:
            matches = matches.iloc[0:0]  # a widely shared mailbox or number is not identity evidence
        results = [self._summary(row) for _, row in matches.iterrows()]
        self._audit(tool_name, normalized, len(results))
        return results

    def find_by_email(self, supplier_id: str) -> list[dict[str, Any]]:
        return self._find_same_contact(supplier_id, "_EMAIL", "find_by_email")

    def find_by_phone(self, supplier_id: str) -> list[dict[str, Any]]:
        return self._find_same_contact(supplier_id, "_PHONE", "find_by_phone")

    def _find_similar(
        self,
        supplier_id: str,
        field: str,
        score_name: str,
        tool_name: str,
        minimum_similarity: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        normalized = self._supplier_id(supplier_id)
        target = self._target(normalized)
        bounded_limit = max(1, min(int(limit), 25))
        if target is None or not target[field] or (not target["_COUNTRY"] and self.detector.config.require_country):
            self._audit(tool_name, normalized, 0)
            return []

        results = []
        country_rows = self.prepared[
            self.prepared["_COUNTRY"].eq(target["_COUNTRY"])
            & self.prepared["SUPPLIER_ID"].astype(str).str.upper().ne(normalized)
            & self.prepared[field].ne("")
        ]
        choices = country_rows[field].astype(str).tolist()
        matches = process.extract(
            str(target[field]),
            choices,
            scorer=fuzz.token_set_ratio,
            score_cutoff=minimum_similarity,
            limit=None,
        )
        for _, similarity, position in matches:
            item = self._summary(country_rows.iloc[position])
            item[score_name] = round(float(similarity), 1)
            results.append(item)
        results.sort(key=lambda item: (-item[score_name], item["SUPPLIER_ID"]))
        results = results[:bounded_limit]
        self._audit(tool_name, normalized, len(results))
        return results

    def find_similar_names(
        self,
        supplier_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self._find_similar(
            supplier_id,
            "_NAME",
            "NAME_SIMILARITY",
            "find_similar_names",
            self.detector.config.name_candidate_threshold,
            limit,
        )

    def find_similar_addresses(
        self,
        supplier_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self._find_similar(
            supplier_id,
            "_ADDRESS",
            "ADDRESS_SIMILARITY",
            "find_similar_addresses",
            self.detector.config.address_candidate_threshold,
            limit,
        )

    @staticmethod
    def _semantic_text(row: pd.Series) -> str:
        return " ".join(
            [
                f"supplier name {row.get('_NAME', '')}",
                f"address {row.get('_ADDRESS', '')}",
                f"category {row.get('SUPPLIER_CATEGORY', '')}",
                f"purchase group {row.get('PURCHASE_GROUP', '')}",
            ]
        ).strip()

    def _get_semantic_index(self) -> SemanticSearchIndex:
        if self._semantic_index is None:
            provider = self._embedding_provider or get_default_embedding_provider()
            texts = {str(row["SUPPLIER_ID"]).strip().upper(): self._semantic_text(row) for _, row in self.prepared.iterrows()}
            self._semantic_index = SemanticSearchIndex(texts, provider)
        return self._semantic_index

    def find_semantic_candidates(
        self,
        supplier_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find same-country suppliers using local embedding similarity."""
        normalized = self._supplier_id(supplier_id)
        target = self._target(normalized)
        if target is None or not self.semantic_enabled or (not target["_COUNTRY"] and self.detector.config.require_country):
            self._audit("find_semantic_candidates", normalized, 0)
            return []
        candidate_rows = self.prepared[
            self.prepared["_COUNTRY"].eq(target["_COUNTRY"]) & self.prepared["SUPPLIER_ID"].astype(str).str.upper().ne(normalized)
        ]
        candidate_ids = {str(value).strip().upper() for value in candidate_rows["SUPPLIER_ID"]}
        index = self._get_semantic_index()
        semantic_results = index.search(
            normalized,
            candidate_ids=candidate_ids,
            limit=limit,
        )
        row_by_id = {str(row["SUPPLIER_ID"]).strip().upper(): row for _, row in candidate_rows.iterrows()}
        results = []
        for match in semantic_results:
            if float(match["similarity"]) < 70.0:
                continue
            item = self._summary(row_by_id[str(match["id"])])
            item["SEMANTIC_SIMILARITY"] = match["similarity"]
            item["EMBEDDING_MODEL"] = index.model_name
            results.append(item)
        self._audit("find_semantic_candidates", normalized, len(results))
        return results

    def get_supplier_activity(self, supplier_id: str) -> dict[str, Any] | None:
        normalized = self._supplier_id(supplier_id)
        target = self._target(normalized)
        if target is None:
            self._audit("get_supplier_activity", normalized, 0)
            return None
        fields = [
            "SUPPLIER_ID",
            "ACTIVE_STATUS",
            "LAST_PO_DATE",
            "PO_COUNT_12M",
            "SPEND_12M_USD",
            "CURRENCY",
        ]
        result = {field: _json_value(target.get(field)) for field in fields}
        self._audit("get_supplier_activity", normalized, 1)
        return result

    def compare_supplier_pair(
        self,
        supplier_id: str,
        candidate_supplier_id: str,
    ) -> dict[str, Any]:
        normalized = self._supplier_id(supplier_id)
        candidate_id = self._supplier_id(candidate_supplier_id)
        left, right = self._target(normalized), self._target(candidate_id)
        if normalized == candidate_id or left is None or right is None:
            raise ValueError("Compare two distinct, known supplier IDs.")
        result = self.detector.score_pair(left, right)
        if not self.semantic_enabled:
            result["SEMANTIC_SIMILARITY"] = None
            result["EMBEDDING_MODEL"] = None
            self._audit("compare_supplier_pair", normalized, 1)
            return {str(key): _json_value(value) for key, value in result.items()}
        semantic_index = self._get_semantic_index()
        semantic_similarity = semantic_index.similarity(
            normalized,
            self._supplier_id(candidate_supplier_id),
        )
        result["SEMANTIC_SIMILARITY"] = semantic_similarity
        result["EMBEDDING_MODEL"] = semantic_index.model_name
        if semantic_similarity >= SEMANTIC_CANDIDATE_THRESHOLD:
            existing_evidence = str(result.get("EVIDENCE", "")).strip()
            semantic_evidence = f"semantic similarity {semantic_similarity:.1f}%"
            result["EVIDENCE"] = "; ".join(value for value in (existing_evidence, semantic_evidence) if value)
        self._audit("compare_supplier_pair", normalized, 1)
        return {str(key): _json_value(value) for key, value in result.items()}

    def qualifies_as_candidate(self, evidence: dict[str, Any]) -> bool:
        """Apply the same inclusion rule used by the batch detector."""
        has_exact_signal = any(
            bool(evidence.get(field))
            for field in (
                "SAME_TAX_ID",
                "SAME_ASSOCIATION_NO",
                "SAME_BANK_ACCOUNT",
                "SAME_EMAIL",
                "SAME_PHONE",
            )
        )
        return (
            has_exact_signal
            or float(evidence["DUPLICATE_SCORE"]) >= self.detector.config.minimum_fuzzy_score
            or float(evidence.get("SEMANTIC_SIMILARITY") or 0.0) >= SEMANTIC_CANDIDATE_THRESHOLD
        )


def create_langchain_supplier_tools(
    service: SupplierDataService,
) -> list[Any]:
    """Expose the allow-listed service operations as typed LangChain tools."""

    @tool
    def get_supplier(supplier_id: str) -> dict[str, Any] | None:
        """Get approved non-sensitive fields for one exact supplier ID."""
        supplier = service.get_supplier(supplier_id)
        if supplier is None:
            return None
        return {field: supplier.get(field) for field in AGENT_SAFE_SUPPLIER_FIELDS}

    @tool
    def find_by_tax_id(supplier_id: str) -> list[dict[str, Any]]:
        """Find suppliers with the same nonblank country-scoped Tax ID."""
        return service.find_by_tax_id(supplier_id)

    @tool
    def find_by_association_no(supplier_id: str) -> list[dict[str, Any]]:
        """Find suppliers with the same nonblank Association Number and country."""
        return service.find_by_association_no(supplier_id)

    @tool
    def find_by_bank_account(supplier_id: str) -> list[dict[str, Any]]:
        """Find suppliers with the same nonblank bank account and bank country."""
        return service.find_by_bank_account(supplier_id)

    @tool
    def find_by_email(supplier_id: str) -> list[dict[str, Any]]:
        """Find suppliers that use the same normalized e-mail address."""
        return service.find_by_email(supplier_id)

    @tool
    def find_by_phone(supplier_id: str) -> list[dict[str, Any]]:
        """Find suppliers that use the same phone number (last nine digits)."""
        return service.find_by_phone(supplier_id)

    @tool
    def find_similar_names(
        supplier_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find up to 25 same-country suppliers with similar normalized names."""
        return service.find_similar_names(supplier_id, limit)

    @tool
    def find_similar_addresses(
        supplier_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find up to 25 same-country suppliers with similar normalized addresses."""
        return service.find_similar_addresses(supplier_id, limit)

    @tool
    def get_supplier_activity(supplier_id: str) -> dict[str, Any] | None:
        """Get approved activity fields for one supplier."""
        return service.get_supplier_activity(supplier_id)

    @tool
    def find_semantic_candidates(
        supplier_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find up to 25 same-country suppliers using local semantic embeddings."""
        return service.find_semantic_candidates(supplier_id, limit)

    @tool
    def compare_supplier_pair(
        supplier_id: str,
        candidate_supplier_id: str,
    ) -> dict[str, Any]:
        """Compare two supplier IDs and return deterministic duplicate evidence."""
        return service.compare_supplier_pair(
            supplier_id,
            candidate_supplier_id,
        )

    return [
        get_supplier,
        find_by_tax_id,
        find_by_association_no,
        find_by_bank_account,
        find_by_email,
        find_by_phone,
        find_similar_names,
        find_similar_addresses,
        find_semantic_candidates,
        get_supplier_activity,
        compare_supplier_pair,
    ]
