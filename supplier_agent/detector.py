"""Deterministic supplier duplicate candidate detection and scoring."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from .normalize import (
    normalize_address,
    normalize_company_name,
    normalize_email,
    normalize_identifier,
    normalize_match_identifier,
    normalize_phone,
)


def token_set_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return float(fuzz.token_set_ratio(left, right))


# Cells evaluated per similarity-matrix chunk (~16 MB of float32 scores).
_CHUNK_CELLS = 4_000_000


def similar_pairs(values: list[str], cutoff: float) -> set[tuple[int, int]]:
    """Return index pairs (i < j) whose token-set similarity reaches ``cutoff``.

    Uses RapidFuzz's vectorized, multi-threaded ``cdist`` in row chunks so a
    country with thousands of suppliers is compared in seconds instead of a
    Python double loop. Blank values never match.
    """
    positions = [index for index, value in enumerate(values) if value]
    texts = [values[index] for index in positions]
    count = len(texts)
    pairs: set[tuple[int, int]] = set()
    if count < 2:
        return pairs
    chunk = max(1, _CHUNK_CELLS // count)
    for start in range(0, count, chunk):
        block = texts[start : start + chunk]
        scores = process.cdist(block, texts, scorer=fuzz.token_set_ratio, score_cutoff=cutoff, dtype=np.float32, workers=-1)
        rows, columns = np.nonzero(scores)
        for row, column in zip(rows.tolist(), columns.tolist()):
            left = start + row
            if left < column:
                pairs.add((positions[left], positions[column]))
    return pairs


@dataclass(frozen=True)
class DetectionConfig:
    name_candidate_threshold: float = 72.0
    address_candidate_threshold: float = 78.0
    name_scoring_floor: float = 70.0
    address_scoring_floor: float = 70.0
    minimum_fuzzy_score: float = 25.0
    medium_threshold: float = 40.0
    high_threshold: float = 65.0
    # When False, records with a blank country are compared with each other.
    # Use it for files that have no country column at all.
    require_country: bool = True
    # An identifier shared by more records than this is treated as a placeholder
    # (for example "0000" or "N/A") instead of producing every pairwise match.
    max_shared_identifier_group: int = 25
    # Points for each signal; the total is capped at 100.
    tax_id_points: float = 25.0
    registration_points: float = 20.0
    bank_points: float = 20.0
    name_points: float = 20.0
    address_points: float = 15.0
    email_points: float = 10.0
    phone_points: float = 10.0


class DuplicateDetector:
    """Find possible duplicates without using AI or evaluation labels."""

    def __init__(self, config: DetectionConfig | None = None) -> None:
        self.config = config or DetectionConfig()

    def prepare(self, suppliers: pd.DataFrame) -> pd.DataFrame:
        prepared = suppliers.copy()
        prepared["_ROW"] = range(len(prepared))
        prepared["_COUNTRY"] = prepared["COUNTRY_CODE"].map(normalize_identifier)
        prepared["_BANK_COUNTRY"] = prepared["BANK_COUNTRY"].map(normalize_identifier)
        prepared["_TAX_ID"] = prepared["TAX_ID"].map(normalize_match_identifier)
        prepared["_ASSOCIATION_NO"] = prepared["ASSOCIATION_NO"].map(normalize_match_identifier)
        prepared["_BANK_ACCOUNT"] = prepared["BANK_ACCOUNT"].map(normalize_match_identifier)
        prepared["_NAME"] = prepared["SUPPLIER_NAME"].map(normalize_company_name)
        prepared["_EMAIL"] = prepared["EMAIL"].map(normalize_email) if "EMAIL" in prepared else ""
        prepared["_PHONE"] = prepared["PHONE"].map(normalize_phone) if "PHONE" in prepared else ""
        self._suppress_shared_values(prepared)
        prepared["_ADDRESS"] = prepared.apply(
            lambda row: normalize_address(
                row.get("ADDRESS_1"),
                row.get("ADDRESS_2"),
                row.get("CITY"),
                row.get("POSTAL_CODE"),
            ),
            axis=1,
        )
        return prepared

    def _suppress_shared_values(self, prepared: pd.DataFrame) -> None:
        """Blank identifier values shared by more records than the configured limit.

        Such values are fillers or shared service accounts ("0000", a payment agent's
        bank account, a generic mailbox). Blanking them here keeps them out of both
        candidate generation and scoring, so a pair found through its name cannot
        collect points from them.
        """
        limit = self.config.max_shared_identifier_group
        for value_column, scope_column in (
            ("_TAX_ID", "_COUNTRY"),
            ("_ASSOCIATION_NO", "_COUNTRY"),
            ("_BANK_ACCOUNT", "_BANK_COUNTRY"),
            ("_EMAIL", None),
            ("_PHONE", None),
        ):
            values = prepared[value_column]
            if not isinstance(values, pd.Series):
                continue
            keys = [scope_column, value_column] if scope_column else [value_column]
            sizes = prepared.groupby(keys, dropna=False, sort=False)[value_column].transform("size")
            prepared[value_column] = values.where(values.eq("") | sizes.le(limit), "")

    def _add_group_pairs(
        self,
        frame: pd.DataFrame,
        group_columns: list[str],
        value_column: str,
        candidates: set[tuple[int, int]],
    ) -> None:
        valid = frame[frame[value_column].ne("")]
        if self.config.require_country:
            valid = valid[valid[group_columns[0]].ne("")]
        valid = valid[valid.duplicated(group_columns, keep=False)]  # only shared values can pair
        for _, group in valid.groupby(group_columns, dropna=False, sort=False):
            rows = group["_ROW"].astype(int).tolist()
            if len(rows) > self.config.max_shared_identifier_group:
                continue  # A value shared this widely is a placeholder, not identity evidence.
            if len(rows) > 1:
                candidates.update(tuple(sorted(pair)) for pair in combinations(rows, 2))

    def _candidate_pairs(self, prepared: pd.DataFrame) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
        exact_candidates: set[tuple[int, int]] = set()
        self._add_group_pairs(prepared, ["_COUNTRY", "_TAX_ID"], "_TAX_ID", exact_candidates)
        self._add_group_pairs(
            prepared,
            ["_COUNTRY", "_ASSOCIATION_NO"],
            "_ASSOCIATION_NO",
            exact_candidates,
        )
        self._add_group_pairs(
            prepared,
            ["_BANK_COUNTRY", "_BANK_ACCOUNT"],
            "_BANK_ACCOUNT",
            exact_candidates,
        )
        # Contact details are global: the same AP mailbox or phone number links records in any country.
        self._add_group_pairs(prepared, ["_EMAIL"], "_EMAIL", exact_candidates)
        self._add_group_pairs(prepared, ["_PHONE"], "_PHONE", exact_candidates)

        fuzzy_candidates: set[tuple[int, int]] = set()
        for _, country_group in prepared.groupby("_COUNTRY", sort=False):
            if not country_group["_COUNTRY"].iloc[0] and self.config.require_country:
                continue  # Missing scope is a quality issue, not evidence of shared country.
            rows = country_group["_ROW"].astype(int).tolist()
            for column, cutoff in (
                ("_NAME", self.config.name_candidate_threshold),
                ("_ADDRESS", self.config.address_candidate_threshold),
            ):
                for left, right in similar_pairs(country_group[column].tolist(), cutoff):
                    fuzzy_candidates.add(tuple(sorted((rows[left], rows[right]))))

        return exact_candidates, fuzzy_candidates

    @staticmethod
    def _same_nonblank(left: str, right: str) -> bool:
        return bool(left) and left == right

    def same_scope(self, left: str, right: str) -> bool:
        """Two records share a country scope (or both lack one when allowed)."""
        if self._same_nonblank(left, right):
            return True
        return not self.config.require_country and not left and not right

    def score_pair(self, left: pd.Series | dict, right: pd.Series | dict) -> dict[str, object]:
        """Score two rows returned by prepare(), without preparing the workbook again."""
        same_country = self.same_scope(left["_COUNTRY"], right["_COUNTRY"])
        same_tax_id = same_country and self._same_nonblank(left["_TAX_ID"], right["_TAX_ID"])
        same_association = same_country and self._same_nonblank(left["_ASSOCIATION_NO"], right["_ASSOCIATION_NO"])
        same_bank = self.same_scope(left["_BANK_COUNTRY"], right["_BANK_COUNTRY"]) and self._same_nonblank(
            left["_BANK_ACCOUNT"], right["_BANK_ACCOUNT"]
        )
        same_email = self._same_nonblank(left.get("_EMAIL", ""), right.get("_EMAIL", ""))
        same_phone = self._same_nonblank(left.get("_PHONE", ""), right.get("_PHONE", ""))
        name_score = token_set_ratio(left["_NAME"], right["_NAME"])
        address_score = token_set_ratio(left["_ADDRESS"], right["_ADDRESS"])

        config = self.config
        score = 0.0
        score += config.tax_id_points if same_tax_id else 0.0
        score += config.registration_points if same_association else 0.0
        score += config.bank_points if same_bank else 0.0
        score += config.email_points if same_email else 0.0
        score += config.phone_points if same_phone else 0.0
        if name_score >= config.name_scoring_floor:
            score += config.name_points * name_score / 100.0
        if address_score >= config.address_scoring_floor:
            score += config.address_points * address_score / 100.0
        score = round(min(score, 100.0), 1)

        if score >= self.config.high_threshold:
            likelihood = "HIGH"
            recommendation = "High likelihood of duplicate; send for Data Steward review."
        elif score >= self.config.medium_threshold:
            likelihood = "MEDIUM"
            recommendation = "Possible duplicate; review the evidence."
        else:
            likelihood = "LOW"
            recommendation = "Weak duplicate signal; review only if business context supports it."

        evidence = []
        if same_tax_id:
            evidence.append("same Tax ID")
        if same_association:
            evidence.append("same Association Number")
        if same_bank:
            evidence.append("same bank account")
        if same_email:
            evidence.append("same email")
        if same_phone:
            evidence.append("same phone")
        if name_score >= self.config.name_scoring_floor:
            evidence.append(f"name similarity {name_score:.1f}%")
        if address_score >= self.config.address_scoring_floor:
            evidence.append(f"address similarity {address_score:.1f}%")

        return {
            "SUPPLIER_ID_A": left["SUPPLIER_ID"],
            "SUPPLIER_NAME_A": left["SUPPLIER_NAME"],
            "SUPPLIER_ID_B": right["SUPPLIER_ID"],
            "SUPPLIER_NAME_B": right["SUPPLIER_NAME"],
            "COUNTRY_CODE": left["COUNTRY_CODE"] if same_country else "",
            "SAME_TAX_ID": same_tax_id,
            "SAME_ASSOCIATION_NO": same_association,
            "SAME_BANK_ACCOUNT": same_bank,
            "SAME_EMAIL": same_email,
            "SAME_PHONE": same_phone,
            "NAME_SIMILARITY": round(name_score, 1),
            "ADDRESS_SIMILARITY": round(address_score, 1),
            "DUPLICATE_SCORE": score,
            "LIKELIHOOD": likelihood,
            "EVIDENCE": "; ".join(evidence),
            "RECOMMENDATION": recommendation,
        }

    def compare_pair(
        self,
        suppliers: pd.DataFrame,
        supplier_id_a: str,
        supplier_id_b: str,
    ) -> dict[str, object]:
        """Compare two approved supplier IDs and return symmetric evidence."""
        prepared = self.prepare(suppliers)
        indexed = {str(row["SUPPLIER_ID"]).strip().upper(): row for _, row in prepared.iterrows()}
        normalized_a = str(supplier_id_a).strip().upper()
        normalized_b = str(supplier_id_b).strip().upper()
        if normalized_a == normalized_b:
            raise ValueError("A supplier cannot be compared with itself.")
        missing = [supplier_id for supplier_id in (normalized_a, normalized_b) if supplier_id not in indexed]
        if missing:
            raise ValueError(f"Unknown supplier ID(s): {missing}")

        result = self.score_pair(indexed[normalized_a], indexed[normalized_b])
        if str(result["SUPPLIER_ID_A"]).upper() != normalized_a:
            result["SUPPLIER_ID_A"], result["SUPPLIER_ID_B"] = (
                result["SUPPLIER_ID_B"],
                result["SUPPLIER_ID_A"],
            )
            result["SUPPLIER_NAME_A"], result["SUPPLIER_NAME_B"] = (
                result["SUPPLIER_NAME_B"],
                result["SUPPLIER_NAME_A"],
            )
        return result

    def detect(self, suppliers: pd.DataFrame, supplier_id: str | None = None) -> pd.DataFrame:
        prepared = self.prepare(suppliers)
        if supplier_id is not None:
            supplier_id = str(supplier_id).strip().upper()
            known_ids = prepared["SUPPLIER_ID"].astype(str).str.upper()
            if supplier_id not in set(known_ids):
                raise ValueError(f"Unknown supplier ID: {supplier_id}")

        exact_candidates, fuzzy_candidates = self._candidate_pairs(prepared)
        all_candidates = exact_candidates | fuzzy_candidates
        records = prepared.to_dict("records")  # positional: _ROW == list index
        results: list[dict[str, object]] = []

        for left_row, right_row in sorted(all_candidates):
            left = records[left_row]
            right = records[right_row]
            if supplier_id is not None and supplier_id not in {
                str(left["SUPPLIER_ID"]).upper(),
                str(right["SUPPLIER_ID"]).upper(),
            }:
                continue
            result = self.score_pair(left, right)
            if supplier_id is not None and str(result["SUPPLIER_ID_B"]).upper() == supplier_id:
                result["SUPPLIER_ID_A"], result["SUPPLIER_ID_B"] = (
                    result["SUPPLIER_ID_B"],
                    result["SUPPLIER_ID_A"],
                )
                result["SUPPLIER_NAME_A"], result["SUPPLIER_NAME_B"] = (
                    result["SUPPLIER_NAME_B"],
                    result["SUPPLIER_NAME_A"],
                )
            is_exact = (left_row, right_row) in exact_candidates
            if is_exact or float(result["DUPLICATE_SCORE"]) >= self.config.minimum_fuzzy_score:
                results.append(result)

        columns = [
            "SUPPLIER_ID_A",
            "SUPPLIER_NAME_A",
            "SUPPLIER_ID_B",
            "SUPPLIER_NAME_B",
            "COUNTRY_CODE",
            "SAME_TAX_ID",
            "SAME_ASSOCIATION_NO",
            "SAME_BANK_ACCOUNT",
            "SAME_EMAIL",
            "SAME_PHONE",
            "NAME_SIMILARITY",
            "ADDRESS_SIMILARITY",
            "DUPLICATE_SCORE",
            "LIKELIHOOD",
            "EVIDENCE",
            "RECOMMENDATION",
        ]
        return pd.DataFrame(results, columns=columns).sort_values(
            ["DUPLICATE_SCORE", "SUPPLIER_ID_A", "SUPPLIER_ID_B"],
            ascending=[False, True, True],
            ignore_index=True,
        )
