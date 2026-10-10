"""Field-by-field comparison of supplier records for side-by-side review."""

from __future__ import annotations

from .columns import FIELD_BY_NAME
from .detector import token_set_ratio
from .normalize import (
    normalize_address,
    normalize_company_name,
    normalize_email,
    normalize_match_identifier,
    normalize_phone,
    normalize_text,
)

COMPARE_FIELDS = (
    "SUPPLIER_NAME",
    "TAX_ID",
    "ASSOCIATION_NO",
    "COUNTRY_CODE",
    "ADDRESS_1",
    "ADDRESS_2",
    "CITY",
    "POSTAL_CODE",
    "BANK_COUNTRY",
    "BANK_ACCOUNT",
    "EMAIL",
    "PHONE",
    "CURRENCY",
    "ACTIVE_STATUS",
    "COMPANY",
    "SITE",
    "CREATED_DATE",
    "LAST_PO_DATE",
    "PO_COUNT_12M",
    "SPEND_12M_USD",
)
IDENTIFIER_FIELDS = {"TAX_ID", "ASSOCIATION_NO", "BANK_ACCOUNT", "COUNTRY_CODE", "BANK_COUNTRY", "POSTAL_CODE", "CURRENCY"}
SENSITIVE_FIELDS = {"BANK_ACCOUNT"}
# Activity and lifecycle fields describe usage, not identity; differences are expected.
CONTEXT_FIELDS = {"ACTIVE_STATUS", "COMPANY", "SITE", "CREATED_DATE", "LAST_PO_DATE", "PO_COUNT_12M", "SPEND_12M_USD"}


def mask(value: object, visible: int = 4) -> str:
    text = str(value or "").strip()
    if len(text) <= visible:
        return text
    return "•" * min(len(text) - visible, 8) + text[-visible:]


def _clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if text.endswith(" 00:00:00"):  # dates exported from Excel as datetimes
        text = text[:-9]
    return "" if text.lower() in {"nan", "none", "<na>", "nat"} else text


def field_status(field: str, left: object, right: object) -> tuple[str, float | None]:
    """Return (status, similarity) where status is match/similar/different/missing/context."""
    a, b = _clean(left), _clean(right)
    if field in CONTEXT_FIELDS:
        return ("context", None)
    if not a or not b:
        return ("missing", None)
    if field in {"EMAIL", "PHONE"}:
        normalizer = normalize_email if field == "EMAIL" else normalize_phone
        same = bool(normalizer(a)) and normalizer(a) == normalizer(b)
        return ("match" if same else "different", 100.0 if same else 0.0)
    if field in IDENTIFIER_FIELDS:
        same = normalize_match_identifier(a) and normalize_match_identifier(a) == normalize_match_identifier(b)
        return ("match" if same else "different", 100.0 if same else 0.0)
    if field == "SUPPLIER_NAME":
        score = token_set_ratio(normalize_company_name(a), normalize_company_name(b))
    elif field in {"ADDRESS_1", "ADDRESS_2", "CITY"}:
        score = token_set_ratio(normalize_address(a), normalize_address(b))
    else:
        score = token_set_ratio(normalize_text(a), normalize_text(b))
    if score >= 99.5:
        return ("match", score)
    if score >= 70:
        return ("similar", score)
    return ("different", score)


def compare_records(left: dict, right: dict, mask_sensitive: bool = True) -> list[dict]:
    """Rows of {FIELD, LABEL, A, B, STATUS, SIMILARITY} for fields present in either record."""
    rows = []
    for field in COMPARE_FIELDS:
        a, b = _clean(left.get(field)), _clean(right.get(field))
        if not a and not b:
            continue
        status, similarity = field_status(field, a, b)
        if mask_sensitive and field in SENSITIVE_FIELDS:
            a, b = mask(a), mask(b)
        rows.append(
            {
                "FIELD": field,
                "LABEL": FIELD_BY_NAME[field].label,
                "A": a,
                "B": b,
                "STATUS": status,
                "SIMILARITY": None if similarity is None else round(similarity, 1),
            }
        )
    return rows


def compare_group(records: list[dict], reference_index: int = 0, mask_sensitive: bool = True) -> list[dict]:
    """Compare several records to one reference (e.g. the suggested survivor).

    Returns rows of {FIELD, LABEL, VALUES: [...], STATUSES: [...]} where the
    reference's own status is ``reference``.
    """
    reference = records[reference_index]
    rows = []
    for field in COMPARE_FIELDS:
        values = [_clean(record.get(field)) for record in records]
        if not any(values):
            continue
        statuses = [
            "reference" if index == reference_index else field_status(field, reference.get(field), record.get(field))[0]
            for index, record in enumerate(records)
        ]
        if mask_sensitive and field in SENSITIVE_FIELDS:
            values = [mask(value) for value in values]
        rows.append({"FIELD": field, "LABEL": FIELD_BY_NAME[field].label, "VALUES": values, "STATUSES": statuses})
    return rows
