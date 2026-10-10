"""Input boundary for supplier data.

Accepts Excel workbooks (.xlsx/.xlsm) and delimited text files (.csv/.tsv/.txt),
maps their columns onto the canonical schema and validates the result.

A sheet named ``Ground_Truth`` is never read here; only the isolated evaluation
module reads labels.
"""

from __future__ import annotations

import csv
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd

from .columns import FIELDS, MATCHING_FIELDS, PROVIDED_FIELDS_ATTR, REQUIRED_FIELDS, apply_mapping, suggest_mapping

SUPPLIER_SHEET = "Supplier_Master"
LABEL_SHEETS = {"GROUND_TRUTH"}
# Kept for backwards compatibility: the columns the matching engine uses.
REQUIRED_COLUMNS = set(MATCHING_FIELDS) | {"SUPPLIER_ID"}

MAX_SUPPLIERS = 20_000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
TEXT_SUFFIXES = {".csv", ".tsv", ".txt"}


def validate_supplier_master(frame: pd.DataFrame) -> pd.DataFrame:
    """Canonicalize IDs once; reject ambiguous keys before any investigation.

    Only SUPPLIER_ID and SUPPLIER_NAME must exist. Other matching columns are
    added as blanks so a file without, say, bank data can still be scanned.
    """
    provided = frame.attrs.get(PROVIDED_FIELDS_ATTR)
    frame = frame.copy().astype("string").fillna("")
    frame.columns = [str(column).strip().upper() for column in frame.columns]
    if provided is None:  # a frame built in code: the columns it has are the ones provided
        provided = tuple(sorted({spec.name for spec in FIELDS} & set(frame.columns)))
    if frame.columns.duplicated().any():
        raise ValueError("The supplier table contains duplicate column names.")
    missing = sorted(set(REQUIRED_FIELDS) - set(frame.columns))
    if missing:
        raise ValueError(f"The supplier table is missing required columns: {missing}")
    for column in sorted(REQUIRED_COLUMNS - set(frame.columns)):
        frame[column] = ""
    frame = frame.astype("string").fillna("")
    if frame.empty:
        raise ValueError("The supplier table contains no supplier records.")
    if len(frame) > MAX_SUPPLIERS:
        raise ValueError(f"At most {MAX_SUPPLIERS:,} suppliers are supported per file; split the file by country or entity.")
    frame["SUPPLIER_ID"] = frame["SUPPLIER_ID"].str.strip().str.upper()
    if frame["SUPPLIER_ID"].eq("").any():
        raise ValueError("SUPPLIER_ID contains missing or blank values.")
    if frame["SUPPLIER_ID"].duplicated().any():
        duplicate_ids = frame.loc[frame["SUPPLIER_ID"].duplicated(keep=False), "SUPPLIER_ID"].unique().tolist()
        raise ValueError(f"SUPPLIER_ID must be unique after trimming and uppercasing. Duplicates: {duplicate_ids[:10]}")
    frame = frame.reset_index(drop=True)
    frame.attrs[PROVIDED_FIELDS_ATTR] = tuple(provided)
    return frame


def _is_excel(raw: bytes) -> bool:
    return raw[:4] == b"PK\x03\x04"


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("The text file encoding could not be read; save it as UTF-8.")


def _read_text(raw: bytes) -> pd.DataFrame:
    text = _decode(raw)
    sample = text[:20_000]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    return pd.read_csv(StringIO(text), sep=delimiter, dtype="string", keep_default_na=False)


def excel_sheet_names(source: str | Path | bytes) -> list[str]:
    """Sheets a user may choose from; label sheets are hidden."""
    handle = BytesIO(source) if isinstance(source, bytes) else source
    with pd.ExcelFile(handle) as workbook:
        return [name for name in workbook.sheet_names if name.strip().upper() not in LABEL_SHEETS]


def default_sheet(sheet_names: list[str]) -> str:
    for name in sheet_names:
        if name.strip().lower() == SUPPLIER_SHEET.lower():
            return name
    preferred = [name for name in sheet_names if name.strip().upper() not in {"README", "DATA_DICTIONARY"}]
    return (preferred or sheet_names)[0]


def _raw_bytes(source: str | Path | bytes) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        if len(source) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Files must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller.")
        return source, ""
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Supplier file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in EXCEL_SUFFIXES | TEXT_SUFFIXES:
        raise ValueError("Input must be an Excel (.xlsx/.xlsm) or CSV/TSV file.")
    return path.read_bytes(), suffix


def read_supplier_table(source: str | Path | bytes, sheet: str | None = None) -> pd.DataFrame:
    """Read the raw table (original headers, all values as text)."""
    raw, suffix = _raw_bytes(source)
    if suffix in EXCEL_SUFFIXES or (not suffix and _is_excel(raw)):
        sheets = excel_sheet_names(raw)
        if not sheets:
            raise ValueError("The workbook has no readable sheets.")
        selected = sheet or default_sheet(sheets)
        if selected.strip().upper() in LABEL_SHEETS or selected not in sheets:
            raise ValueError(f"Sheet not available: {selected}")
        frame = pd.read_excel(BytesIO(raw), sheet_name=selected, dtype="string", keep_default_na=False)
    else:
        frame = _read_text(raw)
    frame = frame.loc[:, [not str(column).startswith("Unnamed:") for column in frame.columns]]
    blank = frame.fillna("").astype(str).apply(lambda column: column.str.strip().eq("")).all(axis=1)
    return frame.loc[~blank].reset_index(drop=True)


def load_supplier_master(
    source: str | Path | bytes,
    mapping: dict[str, str | None] | None = None,
    sheet: str | None = None,
) -> pd.DataFrame:
    """Load, map and validate a supplier table.

    Without an explicit ``mapping`` the columns are mapped automatically from
    known synonyms (canonical names always map to themselves).
    """
    frame = read_supplier_table(source, sheet)
    selected = mapping or suggest_mapping(frame.columns)
    return validate_supplier_master(apply_mapping(frame, selected))


def template_workbook() -> bytes:
    """An empty workbook with every canonical column, for users to fill in."""
    from .columns import FIELDS

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(columns=[spec.name for spec in FIELDS]).to_excel(writer, sheet_name=SUPPLIER_SHEET, index=False)
        pd.DataFrame(
            [
                {
                    "FIELD": spec.name,
                    "REQUIRED": "yes" if spec.required else "no",
                    "USED_FOR_MATCHING": "yes" if spec.used_for_matching else "no",
                    "DESCRIPTION": spec.description,
                }
                for spec in FIELDS
            ]
        ).to_excel(writer, sheet_name="Field_Guide", index=False)
    return buffer.getvalue()
