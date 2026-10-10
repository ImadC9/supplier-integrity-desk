"""Describe a supplier table: how complete each field is and how records spread."""

from __future__ import annotations

import pandas as pd

from .columns import FIELDS, PROVIDED_FIELDS_ATTR


def field_completeness(suppliers: pd.DataFrame, absent_fields: frozenset[str] | set[str] = frozenset()) -> pd.DataFrame:
    """Percentage of records with a value, for every canonical field the file provided."""
    rows = []
    total = len(suppliers)
    for spec in FIELDS:
        if spec.name not in suppliers.columns or spec.name in absent_fields:
            continue
        filled = int(suppliers[spec.name].astype(str).str.strip().ne("").sum())
        rows.append(
            {
                "FIELD": spec.name,
                "LABEL": spec.label,
                "FILLED": filled,
                "BLANK": total - filled,
                "COMPLETENESS": round(100.0 * filled / total, 1) if total else 0.0,
                "USED_FOR_MATCHING": spec.used_for_matching,
            }
        )
    return pd.DataFrame(rows, columns=["FIELD", "LABEL", "FILLED", "BLANK", "COMPLETENESS", "USED_FOR_MATCHING"])


def absent_fields(suppliers: pd.DataFrame) -> frozenset[str]:
    """Canonical fields the source did not provide (not mapped / not a column).

    A field that *was* provided but is blank for every record is not absent:
    it is a data-quality problem and is reported row by row.
    """
    provided = suppliers.attrs.get(PROVIDED_FIELDS_ATTR)
    if provided is None:
        provided = [spec.name for spec in FIELDS if spec.name in suppliers.columns]
    return frozenset(spec.name for spec in FIELDS if spec.name not in set(provided))


def value_counts(suppliers: pd.DataFrame, column: str, top: int = 12, blank_label: str = "(blank)") -> pd.DataFrame:
    if column not in suppliers.columns:
        return pd.DataFrame(columns=["VALUE", "COUNT"])
    values = suppliers[column].astype(str).str.strip().str.upper().replace("", blank_label)
    counts = values.value_counts().head(top)
    return pd.DataFrame({"VALUE": counts.index, "COUNT": counts.values})
