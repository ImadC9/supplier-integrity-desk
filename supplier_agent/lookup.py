"""Check a supplier *before* it is created: does it already exist, and is it valid?"""

from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz, process

from .detector import DetectionConfig, DuplicateDetector
from .io import validate_supplier_master
from .taxid import tax_id_problem
from .validators import iban_problem

NEW_ID = "__NEW_SUPPLIER__"
INPUT_FIELDS = (
    "SUPPLIER_NAME",
    "COUNTRY_CODE",
    "TAX_ID",
    "ASSOCIATION_NO",
    "ADDRESS_1",
    "CITY",
    "POSTAL_CODE",
    "BANK_COUNTRY",
    "BANK_ACCOUNT",
    "EMAIL",
    "PHONE",
)
MATCH_COLUMNS = [
    "SUPPLIER_ID",
    "SUPPLIER_NAME",
    "COUNTRY_CODE",
    "ACTIVE_STATUS",
    "DUPLICATE_SCORE",
    "LIKELIHOOD",
    "EVIDENCE",
    "NAME_SIMILARITY",
    "SHARED_IDENTIFIER",
]


def validate_new_supplier(record: dict) -> list[str]:
    """Format problems in the entered data (empty list when everything looks valid)."""
    problems = []
    if not str(record.get("SUPPLIER_NAME", "")).strip():
        problems.append("Enter the supplier name.")
    tax = tax_id_problem(record.get("COUNTRY_CODE", ""), record.get("TAX_ID", ""))
    if tax:
        problems.append(f"Tax ID {tax}.")
    iban = iban_problem(record.get("BANK_ACCOUNT", ""))
    if iban:
        problems.append(f"Bank account is not a valid IBAN ({iban}).")
    if str(record.get("BANK_ACCOUNT", "")).strip() and not str(record.get("BANK_COUNTRY", "")).strip():
        problems.append("Add the bank country so the bank account can be compared.")
    return problems


def find_existing(suppliers: pd.DataFrame, record: dict, config: DetectionConfig | None = None, limit: int = 10) -> pd.DataFrame:
    """Existing suppliers that may be the same company as ``record``, best first."""
    detector = DuplicateDetector(config)
    entry = {field: str(record.get(field, "") or "").strip() for field in INPUT_FIELDS}
    entry["SUPPLIER_ID"] = NEW_ID
    if not entry["BANK_COUNTRY"] and entry["BANK_ACCOUNT"]:
        entry["BANK_COUNTRY"] = entry["COUNTRY_CODE"]
    master = validate_supplier_master(suppliers)  # the size limit applies to the master, not master + 1
    new_row = {column: "" for column in master.columns} | entry
    frame = pd.concat([master, pd.DataFrame([new_row], columns=master.columns).astype("string")], ignore_index=True)
    prepared = detector.prepare(frame)
    new = prepared.iloc[-1]
    existing = prepared.iloc[:-1]

    candidates: set[int] = set()
    for column in ("_TAX_ID", "_ASSOCIATION_NO", "_BANK_ACCOUNT", "_EMAIL", "_PHONE"):
        if new[column]:
            candidates.update(existing.index[existing[column].eq(new[column])].tolist())
    scope = existing
    if new["_COUNTRY"] or detector.config.require_country:
        scope = existing[existing["_COUNTRY"].eq(new["_COUNTRY"])]
    for column, cutoff in (("_NAME", detector.config.name_candidate_threshold), ("_ADDRESS", detector.config.address_candidate_threshold)):
        if new[column] and len(scope):
            matches = process.extract(new[column], scope[column].tolist(), scorer=fuzz.token_set_ratio, score_cutoff=cutoff, limit=50)
            candidates.update(scope.index[position] for _, _, position in matches)

    rows = []
    for index in candidates:
        other = existing.loc[index]
        result = detector.score_pair(other.to_dict(), new.to_dict())
        if result["EVIDENCE"]:
            rows.append(
                {
                    "SUPPLIER_ID": other["SUPPLIER_ID"],
                    "SUPPLIER_NAME": other["SUPPLIER_NAME"],
                    "COUNTRY_CODE": other["COUNTRY_CODE"],
                    "ACTIVE_STATUS": other.get("ACTIVE_STATUS", ""),
                    "DUPLICATE_SCORE": result["DUPLICATE_SCORE"],
                    "LIKELIHOOD": result["LIKELIHOOD"],
                    "EVIDENCE": result["EVIDENCE"],
                    "NAME_SIMILARITY": result["NAME_SIMILARITY"],
                    "SHARED_IDENTIFIER": any(
                        result[flag] for flag in ("SAME_TAX_ID", "SAME_ASSOCIATION_NO", "SAME_BANK_ACCOUNT", "SAME_EMAIL", "SAME_PHONE")
                    ),
                }
            )
    matches = pd.DataFrame(rows, columns=MATCH_COLUMNS)
    if matches.empty:
        return matches
    return matches.sort_values(["DUPLICATE_SCORE", "SUPPLIER_ID"], ascending=[False, True]).head(limit).reset_index(drop=True)


def verdict(matches: pd.DataFrame) -> str:
    """LIKELY_EXISTS, POSSIBLE_MATCH or NO_MATCH for a lookup result.

    Stricter than the batch scan on purpose: before creating a record, a shared
    identifier or a near-identical name in the same country is reason enough to stop.
    """
    if matches.empty:
        return "NO_MATCH"
    top = matches.iloc[0]
    if top["LIKELIHOOD"] == "HIGH" or bool(matches["SHARED_IDENTIFIER"].any()) or float(matches["NAME_SIMILARITY"].max()) >= 95:
        return "LIKELY_EXISTS"
    return "POSSIBLE_MATCH"
