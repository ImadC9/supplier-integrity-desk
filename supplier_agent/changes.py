"""What changed between two scans of the same supplier master.

A *snapshot* keeps what is needed to compare scans later without storing the
supplier data itself: finding IDs with a short description, supplier names, and
salted hashes of the key fields (so a changed bank account is detected without
the account number being kept).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pandas as pd

from .normalize import normalize_email, normalize_identifier, normalize_phone, normalize_text

TRACKED_FIELDS = (
    "SUPPLIER_NAME",
    "TAX_ID",
    "ASSOCIATION_NO",
    "COUNTRY_CODE",
    "ADDRESS_1",
    "CITY",
    "POSTAL_CODE",
    "BANK_COUNTRY",
    "BANK_ACCOUNT",
    "EMAIL",
    "PHONE",
    "ACTIVE_STATUS",
)
# Changes that deserve attention before the next payment run.
SENSITIVE_CHANGES = {"BANK_ACCOUNT", "BANK_COUNTRY", "TAX_ID", "EMAIL"}
CHANGE_COLUMNS = ["CHANGE", "PRIORITY", "SUPPLIER_ID", "SUPPLIER_NAME", "DETAIL", "FINDING_ID"]


def _normalized(field: str, value: object) -> str:
    if field == "EMAIL":
        return normalize_email(value)
    if field == "PHONE":
        return normalize_phone(value)
    if field in {"TAX_ID", "ASSOCIATION_NO", "BANK_ACCOUNT", "BANK_COUNTRY", "COUNTRY_CODE", "POSTAL_CODE"}:
        return normalize_identifier(value)
    return normalize_text(value)


def _digest(salt: str, field: str, value: object) -> str:
    text = _normalized(field, value)
    return "" if not text else hashlib.sha256(f"{salt}\0{field}\0{text}".encode()).hexdigest()[:20]


def make_snapshot(scan, suppliers: pd.DataFrame, source_name: str = "", salt: str = "") -> dict:
    findings = {
        row.FINDING_ID: {
            "type": row.TYPE,
            "priority": row.PRIORITY,
            "rule": row.RULE_CODE,
            "supplier_id": row.SUPPLIER_ID,
            "supplier_name": row.SUPPLIER_NAME,
            "candidate_id": row.CANDIDATE_ID,
            "summary": row.SUMMARY,
        }
        for row in scan.queue.itertuples(index=False)
    }
    records = {}
    for row in suppliers.to_dict("records"):
        records[str(row["SUPPLIER_ID"])] = {
            "name": str(row.get("SUPPLIER_NAME", "")),
            "hashes": {field: _digest(salt, field, row.get(field, "")) for field in TRACKED_FIELDS if field in row},
        }
    return {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source_name,
        "dataset_id": scan.dataset_id,
        "supplier_count": scan.supplier_count,
        "findings": findings,
        "suppliers": records,
    }


def compare_snapshots(old: dict, new: dict) -> pd.DataFrame:
    """Rows describing new and resolved findings, and added, removed or changed suppliers."""
    rows = []
    old_findings, new_findings = old.get("findings", {}), new.get("findings", {})
    for finding, item in new_findings.items():
        if finding not in old_findings:
            detail = f"{item['type'].replace('_', ' ').title()}: {item['summary']}"
            if item.get("candidate_id"):
                detail = f"Possible duplicate of {item['candidate_id']}: {item['summary']}"
            rows.append(["NEW_FINDING", item["priority"], item["supplier_id"], item["supplier_name"], detail, finding])
    for finding, item in old_findings.items():
        if finding not in new_findings:
            rows.append(
                [
                    "RESOLVED_FINDING",
                    item["priority"],
                    item["supplier_id"],
                    item["supplier_name"],
                    f"No longer found: {item['summary']}",
                    finding,
                ]
            )
    old_suppliers, new_suppliers = old.get("suppliers", {}), new.get("suppliers", {})
    for supplier_id, record in new_suppliers.items():
        previous = old_suppliers.get(supplier_id)
        if previous is None:
            rows.append(["NEW_SUPPLIER", "LOW", supplier_id, record["name"], "Supplier added since the earlier file", ""])
            continue
        changed = [field for field, digest in record["hashes"].items() if previous["hashes"].get(field, digest) != digest]
        if changed:
            sensitive = [field for field in changed if field in SENSITIVE_CHANGES]
            detail = "Changed: " + ", ".join(field.replace("_", " ").title() for field in changed)
            if "BANK_ACCOUNT" in changed:
                detail += ". Bank details changed — confirm with the supplier through a known contact before paying."
            rows.append(["CHANGED_SUPPLIER", "HIGH" if sensitive else "LOW", supplier_id, record["name"], detail, ""])
    for supplier_id, record in old_suppliers.items():
        if supplier_id not in new_suppliers:
            rows.append(["REMOVED_SUPPLIER", "LOW", supplier_id, record["name"], "Supplier no longer in the file", ""])
    frame = pd.DataFrame(rows, columns=CHANGE_COLUMNS)
    if not frame.empty:
        order = {"NEW_FINDING": 0, "CHANGED_SUPPLIER": 1, "RESOLVED_FINDING": 2, "NEW_SUPPLIER": 3, "REMOVED_SUPPLIER": 4}
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        frame = (
            frame.assign(_o=frame["CHANGE"].map(order), _r=frame["PRIORITY"].map(rank))
            .sort_values(["_o", "_r", "SUPPLIER_ID"])
            .drop(columns=["_o", "_r"])
            .reset_index(drop=True)
        )
    return frame


def change_summary(changes: pd.DataFrame) -> dict[str, int]:
    counts = changes["CHANGE"].value_counts().to_dict() if not changes.empty else {}
    sensitive = int((changes["CHANGE"].eq("CHANGED_SUPPLIER") & changes["PRIORITY"].eq("HIGH")).sum()) if not changes.empty else 0
    return {
        "new_findings": counts.get("NEW_FINDING", 0),
        "resolved_findings": counts.get("RESOLVED_FINDING", 0),
        "new_suppliers": counts.get("NEW_SUPPLIER", 0),
        "removed_suppliers": counts.get("REMOVED_SUPPLIER", 0),
        "changed_suppliers": counts.get("CHANGED_SUPPLIER", 0),
        "sensitive_changes": sensitive,
    }
