"""Spreadsheet-friendly exports that never execute free-text formulas."""

import pandas as pd

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """Prefix text that a spreadsheet would treat as a formula (CSV/Excel injection)."""
    if isinstance(value, str) and value.lstrip(" ").startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_text(frame: pd.DataFrame) -> str:
    return frame.map(safe_cell).to_csv(index=False)
