"""Supplier Integrity Desk — Streamlit interface.

Run with:  supplier-desk app   (or: streamlit run streamlit_app.py from a clone)

Streamlit is only the presentation layer. Matching, quality rules, clustering,
the LangGraph investigation and the review history live in ``supplier_agent``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from sqlite3 import Error as DatabaseError
from typing import Any

import pandas as pd
import streamlit as st

from supplier_agent import __version__
from supplier_agent import ui_render as ui
from supplier_agent.actions import action_plan
from supplier_agent.changes import change_summary, compare_snapshots, make_snapshot
from supplier_agent.columns import FIELD_BY_NAME, FIELDS, apply_mapping, missing_required, suggest_mapping
from supplier_agent.compare import compare_group, compare_records
from supplier_agent.database import describe as describe_database
from supplier_agent.database import read_query
from supplier_agent.detector import DetectionConfig
from supplier_agent.exports import csv_text
from supplier_agent.i18n import LANGUAGES, TranslatedStreamlit, Translator
from supplier_agent.io import (
    MAX_SUPPLIERS,
    MAX_UPLOAD_BYTES,
    _is_excel,
    default_sheet,
    excel_sheet_names,
    read_supplier_table,
    template_workbook,
    validate_supplier_master,
)
from supplier_agent.lookup import find_existing, validate_new_supplier, verdict
from supplier_agent.paths import EXAMPLE_DB, PREVIOUS_SAMPLE, SAMPLE_WORKBOOK
from supplier_agent.quality import RULE_DESCRIPTIONS, QualityConfig
from supplier_agent.reports import build_excel_report
from supplier_agent.review_store import QUALITY_DECISIONS, ReviewStore
from supplier_agent.triage import dataset_fingerprint, finding_id, scan_suppliers
from supplier_agent.ui_charts import horizontal_bars, priority_bars
from supplier_agent.ui_session import InvestigationSession
from supplier_agent.workflow.nodes import ALLOWED_REVIEW_DECISIONS

# Decisions are kept next to where the app is started unless SUPPLIER_REVIEW_DB is set.
DEFAULT_DB = Path.cwd() / "outputs" / "reviews.sqlite3"
DEMO_SUPPLIER = "S100118"
NOT_MAPPED = "— not in file —"
PAGES = ["Overview", "Review queue", "Clusters", "What's new", "Check a supplier", "Investigation", "Review history", "Guide"]
DECISION_LABELS = {
    "CONFIRM_DUPLICATE": "Confirm duplicate",
    "NOT_DUPLICATE": "Not a duplicate",
    "NEEDS_INVESTIGATION": "Needs investigation",
    "FIX_REQUIRED": "Fix required",
    "ACCEPTED_EXCEPTION": "Accepted exception",
    "UNREVIEWED": "Unreviewed",
}

st.set_page_config(
    page_title="Supplier Integrity Desk",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": f"Supplier Integrity Desk {__version__} — explainable supplier duplicate "
        "and data-quality review. Source data is never modified."
    },
)

# Every label below goes through the translator; `st` becomes a translating proxy.
_raw_st = st


def _default_language() -> str:
    """?lang=es in the URL, then SUPPLIER_DESK_LANG, then the browser language, then English."""
    candidates = [_raw_st.query_params.get("lang", ""), os.environ.get("SUPPLIER_DESK_LANG", "")]
    try:
        candidates.append(_raw_st.context.locale or "")
    except Exception:  # noqa: BLE001 - not available in every runtime
        pass
    for candidate in candidates:
        code = str(candidate or "")[:2].lower()
        if code in LANGUAGES:
            return code
    return "en"


if "language" not in st.session_state:
    st.session_state.language = _default_language()
t = Translator(st.session_state.get("language", "en"))
st = TranslatedStreamlit(_raw_st, t)

# Visual style: light ruled paper, deep navy and blue, amber highlights,
# compact tabular figures and square panels.
st.markdown(
    """
    <style>
    :root { --ink:#102a43; --navy:#0b3558; --blue:#146b8c; --cyan:#51a9bd; --paper:#f5f8f4; --panel:rgba(255,255,255,.66);
            --line:#c8d8d8; --amber:#e1a72c; --muted:#5f7180; --high:#b8322a; --medium:#b07a00; --low:#1f78a8;
            --ok:#2f7d4f; }
    .stApp { color:var(--ink); background-color:var(--paper);
      background-image:linear-gradient(rgba(20,107,140,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(20,107,140,.05) 1px,transparent 1px);
      background-size:28px 28px,28px 28px; }
    [data-testid="stHeader"] { background:rgba(245,248,244,.92); }
    [data-testid="stSidebar"] { background:#eef3f0; border-right:1px solid var(--line); }
    [data-testid="stSidebar"] h2 { font-size:.78rem; letter-spacing:.16em; text-transform:uppercase; color:var(--blue); margin:.6rem 0 0; }
    [data-testid="stMainBlockContainer"] { max-width:1320px; padding-top:2.2rem; padding-bottom:5rem; }
    h1,h2,h3 { color:var(--navy); letter-spacing:-.02em; }
    h1 { font-size:2rem!important; line-height:1.1!important; padding-bottom:0!important; }
    .brand { font-weight:800; color:var(--navy); font-size:1.05rem; letter-spacing:-.01em; }
    .brand small { display:block; font-weight:500; color:var(--muted); font-size:.75rem; letter-spacing:0; }
    .eyebrow { color:var(--blue); font-size:.72rem; font-weight:800; letter-spacing:.18em; text-transform:uppercase; }
    .deck { color:var(--muted); font-size:1.02rem; max-width:52rem; margin:.4rem 0 .9rem; }
    .dataset-bar { display:flex; flex-wrap:wrap; gap:.4rem 1.4rem; align-items:center; border-top:2px solid var(--amber);
      border-bottom:1px solid var(--line); padding:.55rem 0; margin:.2rem 0 1rem; font-size:.84rem; color:var(--muted); }
    .dataset-bar b { color:var(--navy); }
    .tag { display:inline-block; padding:.08rem .5rem; border:1px solid var(--line); border-radius:2px; background:#fff;
      font-size:.72rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--blue); }
    .tag.warn { color:#7a5300; border-color:#e8cf95; background:#fff8e6; }
    div[role="radiogroup"][aria-label="Workspace"] { gap:0; border-bottom:1px solid var(--line); flex-wrap:wrap; }
    div[role="radiogroup"][aria-label="Workspace"] label { padding:.5rem 1rem .55rem; margin:0 0 -1px; border-bottom:3px solid transparent; cursor:pointer; }
    div[role="radiogroup"][aria-label="Workspace"] label:hover p { color:var(--navy); }
    div[role="radiogroup"][aria-label="Workspace"] label p { color:var(--muted); font-weight:600; }
    div[role="radiogroup"][aria-label="Workspace"] label[data-selected="true"] { border-bottom-color:var(--navy); }
    div[role="radiogroup"][aria-label="Workspace"] label[data-selected="true"] p { color:var(--navy); font-weight:780; }
    div[role="radiogroup"][aria-label="Workspace"] label > div > div > div:not([data-testid="stMarkdownContainer"]) { display:none; }
    .kpis { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); background:var(--panel); margin:.4rem 0 1.2rem; }
    .kpi { padding:.9rem 1rem; border-right:1px solid var(--line); }
    .kpi:last-child { border-right:none; }
    .kpi-label { display:block; font-size:.66rem; text-transform:uppercase; letter-spacing:.12em; color:var(--muted); font-weight:700; }
    .kpi-value { display:block; font-size:1.9rem; font-weight:780; color:var(--navy); font-variant-numeric:tabular-nums; line-height:1.15; margin-top:.25rem; }
    .kpi-foot { display:block; font-size:.76rem; color:var(--muted); margin-top:.15rem; }
    .section-kicker { color:var(--blue); font-weight:800; text-transform:uppercase; letter-spacing:.14em; font-size:.68rem; margin:1.2rem 0 .1rem; }
    .chip { display:inline-block; min-width:4.2rem; text-align:center; padding:.1rem .45rem; border-radius:2px; font-size:.7rem; font-weight:800; letter-spacing:.08em; color:#fff; }
    .chip-high { background:var(--high); } .chip-medium { background:var(--medium); } .chip-low { background:var(--low); }
    .table-scroll { overflow-x:auto; border:1px solid var(--line); background:var(--panel); margin:.4rem 0 .8rem; }
    table.cmp { border-collapse:collapse; width:100%; font-size:.86rem; }
    table.cmp th, table.cmp td { padding:.42rem .7rem; border-bottom:1px solid #e1eaea; text-align:left; vertical-align:top; overflow-wrap:anywhere; }
    table.cmp thead th { background:#e8efed; color:var(--navy); font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; }
    table.cmp tbody th { color:var(--muted); font-weight:600; width:11rem; white-space:nowrap; }
    table.cmp tr.row-match td:not(.cmp-status) { background:rgba(47,125,79,.07); }
    table.cmp tr.row-similar td:not(.cmp-status) { background:rgba(225,167,44,.10); }
    table.cmp tr.row-context td, table.cmp tr.row-context th { color:var(--muted); }
    .cmp-badge { display:inline-block; font-size:.72rem; font-weight:700; white-space:nowrap; padding:.05rem .4rem; border-radius:2px; border:1px solid var(--line); background:#fff; }
    .cmp-match { color:var(--ok); border-color:#b9d8c4; } .cmp-similar { color:#8a5d00; border-color:#ecd39b; }
    .cmp-different { color:var(--muted); } .cmp-missing { color:#90a0aa; }
    td.cell-match { background:rgba(47,125,79,.07); } td.cell-similar { background:rgba(225,167,44,.10); }
    td.cell-reference { background:rgba(11,53,88,.06); font-weight:650; }
    .cell-mark { font-size:.8rem; border:none; background:none; padding:0; }
    .cmp-legend { display:flex; gap:.4rem; flex-wrap:wrap; margin:.2rem 0; }
    .empty-note { color:var(--muted); padding:.8rem 0; }
    .route { display:grid; grid-template-columns:repeat(5,1fr); margin:.6rem 0 1.2rem; border-top:1px solid var(--line); border-bottom:1px solid var(--line); background:rgba(255,255,255,.42); }
    .route-step { padding:.8rem .65rem; position:relative; color:#70808c; }
    .route-step:not(:last-child)::after { content:""; position:absolute; width:100%; height:2px; top:1.2rem; left:50%; background:var(--line); z-index:0; }
    .route-step.done:not(:last-child)::after { background:var(--cyan); }
    .route-dot { display:block; width:.85rem; height:.85rem; border-radius:50%; background:var(--paper); border:2px solid var(--line); position:relative; z-index:1; }
    .route-step.done .route-dot { background:var(--cyan); border-color:var(--blue); }
    .route-step.current .route-dot { background:var(--amber); border-color:#9d6b08; }
    .route-label { display:block; margin-top:.5rem; font-size:.72rem; font-weight:750; }
    .route-number { display:block; font-size:.64rem; letter-spacing:.1em; opacity:.78; }
    .record-strip { display:grid; grid-template-columns:2fr repeat(4,1fr); border:1px solid var(--line); background:var(--panel); margin:.5rem 0 1.2rem; }
    .record-cell { padding:.85rem 1rem; border-right:1px solid var(--line); }
    .record-cell:last-child { border-right:none; }
    .record-label { display:block; color:var(--muted); font-size:.65rem; text-transform:uppercase; letter-spacing:.1em; }
    .record-value { display:block; color:var(--navy); font-weight:760; margin-top:.25rem; overflow-wrap:anywhere; }
    .analysis-box { border-top:2px solid var(--cyan); background:var(--panel); padding:1rem 1.2rem; line-height:1.55; }
    .policy-item { border-top:1px solid var(--line); padding:.8rem 0; }
    .policy-cite { color:var(--navy); font-weight:760; }
    .policy-meta { color:var(--muted); font-size:.76rem; margin-top:.35rem; }
    .survivor { border-left:3px solid var(--amber); padding:.5rem .9rem; background:var(--panel); margin:.4rem 0 .8rem; }
    [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"], [data-testid="stButton"] button[kind="primary"] { background:var(--navy); border-color:var(--navy); border-radius:3px; color:#fff; }
    [data-testid="stDownloadButton"] button { border-radius:3px; }
    [data-testid="stDataFrame"] { border:1px solid var(--line); }
    @media (max-width:900px) {
      .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .kpi { border-bottom:1px solid var(--line); }
      .record-strip { grid-template-columns:1fr 1fr; }
      .record-cell { border-bottom:1px solid var(--line); }
      .record-cell:first-child { grid-column:1/-1; }
    }
    @media (max-width:640px) {
      [data-testid="stMainBlockContainer"] { padding:3rem 1rem 3rem; }
      h1 { font-size:1.8rem!important; }
      .route { grid-template-columns:1fr; }
      .route-step { display:flex; gap:.6rem; align-items:center; padding:.4rem .65rem; }
      .route-step::after { display:none; }
      .route-label { margin-top:0; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# Hosted deployments (e.g. Streamlit Community Cloud) keep credentials in
# st.secrets; the analysis provider reads environment variables.
try:
    for _name in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        if _name in st.secrets and not os.environ.get(_name):
            os.environ[_name] = str(st.secrets[_name])
except Exception:  # noqa: BLE001 - no secrets file is the normal local case
    pass


# ---------------------------------------------------------------- helpers
@st.cache_data(show_spinner=False, max_entries=8)
def _read_table(contents: bytes, sheet: str | None) -> pd.DataFrame:
    return read_supplier_table(contents, sheet)


@st.cache_data(show_spinner=False, max_entries=8)
def _sheets(contents: bytes) -> list[str]:
    return excel_sheet_names(contents) if _is_excel(contents) else []


def _read_database(connection: str, query: str) -> pd.DataFrame:
    return read_query(connection, query)


def _label(value: Any) -> str:
    return DECISION_LABELS.get(str(value), str(value).replace("_", " ").title())


SETTING_KEYS = (
    "cfg_high",
    "cfg_medium",
    "cfg_name",
    "cfg_address",
    "cfg_no_country",
    "cfg_cluster",
    "cfg_required",
    "cfg_missing_ids",
    "cfg_formats",
    "cfg_placeholders",
    "cfg_ibans",
    "cfg_tax_ids",
    "mask_sensitive",
)


def _load_profile() -> None:
    upload = st.session_state.get("profile_upload")
    if upload is None:
        return
    try:
        profile = json.loads(upload.getvalue().decode("utf-8"))
        if profile.get("app") != "supplier-integrity-desk":
            raise ValueError("not a Supplier Integrity Desk settings file")
        st.session_state.pending_profile = profile
        st.session_state.profile_message = ("success", t("Settings loaded."))
    except (ValueError, UnicodeDecodeError, AttributeError) as error:
        st.session_state.profile_message = ("error", t("Settings could not be loaded: {error}", error=error))


def _store() -> ReviewStore:
    return ReviewStore(os.environ.get("SUPPLIER_REVIEW_DB") or str(DEFAULT_DB))


def _open_investigation(supplier_id: str, candidate_id: str | None) -> None:
    st.session_state.pending_supplier = supplier_id
    st.session_state.pending_candidate = candidate_id
    st.session_state.page = "Investigation"
    st.session_state.pop("investigation_session", None)


def _go(page: str) -> None:
    st.session_state.page = page


def _records_by_id(suppliers: pd.DataFrame, ids: list[str]) -> list[dict]:
    indexed = suppliers.set_index("SUPPLIER_ID", drop=False)
    return [indexed.loc[supplier_id].to_dict() for supplier_id in ids if supplier_id in indexed.index]


# ---------------------------------------------------------------- sidebar: data
with st.sidebar:
    st.markdown(
        f'<div class="brand">🔎 Supplier Integrity Desk<small>v{__version__} · {t("runs locally · read-only")}</small></div>',
        unsafe_allow_html=True,
    )
    st.selectbox("Language", list(LANGUAGES), format_func=LANGUAGES.get, key="language")
    st.header("Data")
    source = st.radio(
        "Dataset",
        ["Sample data", "Upload a file", "Database"],
        key="source",
        horizontal=True,
        help="The sample is 1,000 fictional suppliers with planted duplicates and data issues.",
    )
    uploaded = None
    if source == "Upload a file":
        uploaded = st.file_uploader(
            "Supplier list (.xlsx, .xlsm, .csv, .tsv)",
            type=["xlsx", "xlsm", "csv", "tsv", "txt"],
            key="workbook_upload",
            help=t(
                "Up to {mb} MB and {count} suppliers. Use approved or anonymized data.",
                mb=MAX_UPLOAD_BYTES // (1024 * 1024),
                count=f"{MAX_SUPPLIERS:,}",
            ),
        )
        st.download_button(
            "Download blank template", template_workbook(), "supplier_template.xlsx", key="download_template", width="stretch"
        )
    elif source == "Database":
        with st.form("database_source", border=False):
            db_connection = st.text_input(
                "Connection",
                value=os.environ.get("SUPPLIER_DESK_DB_URL", str(EXAMPLE_DB) if EXAMPLE_DB.exists() else ""),
                type="password",
                help="A SQLite file path, or a SQLAlchemy URL such as postgresql://user:password@host/db "
                "(needs the 'database' extra and a driver). Use a read-only account.",
            )
            db_query = st.text_area("Query (one read-only SELECT)", value="SELECT * FROM vendors", height=90)
            if st.form_submit_button("Load from database", type="primary", width="stretch"):
                try:
                    st.session_state.db_frame = _read_database(db_connection, db_query)
                    st.session_state.db_label = describe_database(db_connection)
                    st.session_state.db_key = hashlib.sha256(f"{db_connection}\0{db_query}".encode()).hexdigest()
                except Exception as error:  # noqa: BLE001 - shown to the user
                    st.session_state.pop("db_frame", None)
                    st.error(t("The query could not be run: {error}", error=error))

waiting = (source == "Upload a file" and uploaded is None) or (source == "Database" and "db_frame" not in st.session_state)
if waiting:
    st.title("Supplier Integrity Desk")
    st.markdown(
        '<div class="deck">Upload a supplier or vendor export from any ERP, or read it from a database, in the sidebar. '
        "Columns are mapped automatically and you can correct the mapping before scanning. Or switch back to the sample data.</div>",
        unsafe_allow_html=True,
    )
    st.info("Choose a file or run a database query in the sidebar, or select **Sample data** to explore the tool.")
    st.stop()

sheet = None
try:
    if source == "Database":
        raw = st.session_state.db_frame
        source_name = st.session_state.db_label
        source_key = st.session_state.db_key
    else:
        contents = uploaded.getvalue() if uploaded is not None else SAMPLE_WORKBOOK.read_bytes()
        source_name = uploaded.name if uploaded is not None else t("Sample data (fictional)")
        source_key = hashlib.sha256(contents).hexdigest()
        if len(contents) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Files must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller.")
        sheets = _sheets(contents)
        with st.sidebar:
            if len(sheets) > 1:
                sheet = st.selectbox("Sheet", sheets, index=sheets.index(default_sheet(sheets)), key=f"sheet_{source_key[:12]}")
            elif sheets:
                sheet = sheets[0]
        raw = _read_table(contents, sheet)
except Exception as error:  # noqa: BLE001 - shown to the user
    st.error(t("The file could not be read: {error}", error=error))
    st.stop()

suggested = suggest_mapping(raw.columns)
columns = [str(column) for column in raw.columns]
mapping_prefix = f"map_{source_key[:12]}_{sheet or ''}_"
_profile = st.session_state.get("pending_profile")
if _profile:  # a loaded settings profile sets the mapping before the widgets exist
    for _field, _column in (_profile.get("mapping") or {}).items():
        if _field in FIELD_BY_NAME:
            st.session_state[mapping_prefix + _field] = _column if _column in columns else NOT_MAPPED
with st.sidebar:
    unmapped_required = missing_required(suggested)
    with st.expander("Column mapping", expanded=bool(unmapped_required)):
        st.caption("Matched automatically from common ERP names. Correct anything that looks wrong.")
        mapping: dict[str, str | None] = {}
        for spec in FIELDS:
            options = [NOT_MAPPED] + columns
            default = suggested.get(spec.name)
            choice = st.selectbox(
                t(spec.label) + (" *" if spec.required else ""),
                options,
                index=options.index(default) if default in options else 0,
                key=mapping_prefix + spec.name,
                help=t(spec.description),
            )
            mapping[spec.name] = None if choice == NOT_MAPPED else choice
    mapped_count = sum(1 for value in mapping.values() if value)
    st.caption(t("{mapped} of {total} fields mapped · {rows} rows", mapped=mapped_count, total=len(FIELDS), rows=f"{len(raw):,}"))

try:
    if missing_required(mapping):
        raise ValueError(
            t("Map the required fields marked * in the sidebar: ")
            + ", ".join(t(FIELD_BY_NAME[name].label) for name in missing_required(mapping))
            + "."
        )
    mapping_key = json.dumps(mapping, sort_keys=True)
    if st.session_state.get("loaded_key") != (source_key, sheet, mapping_key):
        suppliers = validate_supplier_master(apply_mapping(raw, mapping))
        st.session_state.suppliers = suppliers
        st.session_state.dataset_id = dataset_fingerprint(suppliers)
        st.session_state.loaded_key = (source_key, sheet, mapping_key)
        for key in ("scan_result", "scan_key", "investigation_session", "pending_supplier", "pending_candidate"):
            st.session_state.pop(key, None)
    suppliers: pd.DataFrame = st.session_state.suppliers
    dataset_id: str = st.session_state.dataset_id
    store = _store()
except Exception as error:  # noqa: BLE001 - shown to the user
    st.title("Supplier Integrity Desk")
    st.error(t("The supplier table could not be loaded: {error}", error=error))
    st.stop()

# ---------------------------------------------------------------- sidebar: settings
has_country = bool(mapping.get("COUNTRY_CODE")) and suppliers["COUNTRY_CODE"].str.strip().ne("").any()
if _profile:
    for _key, _value in (_profile.get("settings") or {}).items():
        if _key in SETTING_KEYS:
            st.session_state[_key] = _value
    st.session_state.pop("pending_profile", None)
with st.sidebar:
    st.header("Matching")
    with st.expander("Duplicate rules", expanded=False):
        high = st.slider("High priority from score", 30, 100, 65, key="cfg_high")
        medium = st.slider("Medium priority from score", 10, 100, 40, key="cfg_medium")
        name_cut = st.slider(
            "Name similarity to compare (%)",
            50,
            100,
            72,
            key="cfg_name",
            help="Records whose normalized names reach this similarity become candidate pairs.",
        )
        address_cut = st.slider("Address similarity to compare (%)", 50, 100, 78, key="cfg_address")
        no_country = st.checkbox(
            "Compare records without a country",
            value=not has_country,
            key="cfg_no_country",
            help="By default matching happens within a country. Turn this on for files without countries.",
        )
        cluster_level = st.radio(
            "Cluster pairs of priority",
            ["HIGH", "MEDIUM"],
            horizontal=True,
            key="cfg_cluster",
            format_func=lambda v: "High only" if v == "HIGH" else "High + medium",
        )
    with st.expander("Quality rules", expanded=False):
        required = st.multiselect(
            "Required fields",
            [spec.name for spec in FIELDS if spec.name != "SUPPLIER_ID"],
            default=["SUPPLIER_NAME", "COUNTRY_CODE", "ADDRESS_1", "CITY"],
            key="cfg_required",
            format_func=lambda name: t(FIELD_BY_NAME[name].label),
        )
        missing_ids = st.checkbox("Flag missing tax / registration IDs", True, key="cfg_missing_ids")
        formats = st.checkbox("Check country & currency code formats", True, key="cfg_formats")
        placeholders = st.checkbox("Flag placeholder IDs (N/A, 0000…)", True, key="cfg_placeholders")
        ibans = st.checkbox("Validate IBAN check digits", True, key="cfg_ibans")
        tax_ids = st.checkbox("Validate tax / VAT numbers by country", True, key="cfg_tax_ids")
    st.header("Privacy")
    mask_sensitive = st.toggle("Mask bank accounts", True, key="mask_sensitive", help="Shows only the last four characters on screen.")
    st.caption(
        "Files stay in this app's memory. Decisions are stored in a local SQLite file. "
        "Nothing is sent to an AI service unless you choose Gemini in an investigation."
    )
    st.header("Settings profile")
    st.caption("Save the column mapping and rules to reuse them for next month's export, or share them with your team.")
    st.download_button(
        "Save settings (JSON)",
        json.dumps(
            {
                "app": "supplier-integrity-desk",
                "version": 1,
                "mapping": mapping,
                "settings": {key: st.session_state.get(key) for key in SETTING_KEYS if key in st.session_state},
            },
            indent=2,
            default=list,
        ),
        "supplier_desk_settings.json",
        "application/json",
        key="download_profile",
        width="stretch",
    )
    st.file_uploader("Load settings", type=["json"], key="profile_upload", on_change=_load_profile, label_visibility="collapsed")
    if "profile_message" in st.session_state:
        _kind, _text = st.session_state.pop("profile_message")
        (st.success if _kind == "success" else st.error)(_text)

detection_config = DetectionConfig(
    name_candidate_threshold=float(name_cut),
    address_candidate_threshold=float(address_cut),
    medium_threshold=float(min(medium, high)),
    high_threshold=float(high),
    require_country=not no_country,
)
quality_config = QualityConfig(
    required_fields=tuple(required),
    review_missing_identifiers=missing_ids,
    check_code_formats=formats,
    check_placeholders=placeholders,
    check_ibans=ibans,
    check_tax_ids=tax_ids,
)
scan_key = (dataset_id, json.dumps(asdict(detection_config), sort_keys=True), repr(quality_config), cluster_level)
if st.session_state.get("scan_key") != scan_key:
    with st.spinner(t("Scanning {count} suppliers for duplicates and data-quality issues…", count=f"{len(suppliers):,}")):
        st.session_state.scan_result = scan_suppliers(suppliers, quality_config, detection_config, cluster_level)
    st.session_state.scan_key = scan_key
    try:  # keep a privacy-safe snapshot so the next file can be compared with this one
        store.save_snapshot(make_snapshot(st.session_state.scan_result, suppliers, source_name, store.salt()))
    except (OSError, DatabaseError):
        pass
scan = st.session_state.scan_result
latest = store.latest(dataset_id)
earlier = store.latest_elsewhere(dataset_id)

# ---------------------------------------------------------------- masthead
st.title("Supplier Integrity Desk")
st.markdown(
    '<div class="deck">Find duplicate suppliers and incomplete records, see exactly why each one was flagged, '
    "and record a human decision. Your source data is never changed.</div>",
    unsafe_allow_html=True,
)
if source == "Sample data":
    source_tag = '<span class="tag">Sample · fictional</span>'
    source_note = "Demo workspace — fictional suppliers and example policies; no real data."
else:
    source_tag = '<span class="tag warn">Your file</span>'
    source_note = "Local review workspace — the bundled policies are examples; replace them with your own."
st.markdown(
    f'<div class="dataset-bar">{source_tag}<span><b>{ui.safe(source_name)}</b></span>'
    f"<span><b>{scan.supplier_count:,}</b> {t('suppliers')}</span><span>{t('Dataset')} <b>{dataset_id[:10]}</b></span>"
    f"<span>{t(source_note)}</span></div>",
    unsafe_allow_html=True,
)
if source != "Sample data" and scan.absent_fields & {"TAX_ID", "ASSOCIATION_NO", "BANK_ACCOUNT", "COUNTRY_CODE"}:
    missing_labels = ", ".join(
        t(FIELD_BY_NAME[name].label) for name in sorted(scan.absent_fields & {"TAX_ID", "ASSOCIATION_NO", "BANK_ACCOUNT", "COUNTRY_CODE"})
    )
    st.warning(
        t(
            "Not in this file: {labels}. Matching relies on the remaining fields; map them in the sidebar if they exist under another name.",
            labels=missing_labels,
        )
    )

page = st.radio("Workspace", PAGES, horizontal=True, key="page", label_visibility="collapsed")

# Review status for every finding (latest decision wins).
queue = scan.queue.copy()
queue["REVIEW_STATUS"] = queue["FINDING_ID"].map(lambda key: latest.get(key, {}).get("decision", "UNREVIEWED"))


# ================================================================= OVERVIEW
def render_overview() -> None:
    pairs = scan.duplicate_pairs
    high_pairs = int(pairs["LIKELIHOOD"].eq("HIGH").sum()) if not pairs.empty else 0
    in_clusters = int(scan.clusters["SIZE"].sum()) if not scan.clusters.empty else 0
    reviewed = int(queue["REVIEW_STATUS"].ne("UNREVIEWED").sum())
    share = f"{100 * reviewed / len(queue):.0f}%" if len(queue) else "—"
    st.markdown(
        ui.kpi_tiles(
            [
                (t("Suppliers"), f"{scan.supplier_count:,}", t("{count} fields mapped", count=len(scan.completeness))),
                (t("High-priority pairs"), f"{high_pairs:,}", t("{count} candidate pairs in total", count=f"{len(pairs):,}")),
                (t("Duplicate clusters"), f"{len(scan.clusters):,}", t("{count} suppliers involved", count=f"{in_clusters:,}")),
                (
                    t("Quality findings"),
                    f"{len(scan.quality_findings):,}",
                    t(
                        "{count} suppliers affected",
                        count=f"{scan.quality_findings['SUPPLIER_ID'].nunique() if len(scan.quality_findings) else 0:,}",
                    ),
                ),
                (t("Reviewed"), share, t("{done} of {total} findings", done=f"{reviewed:,}", total=f"{len(queue):,}")),
            ]
        ),
        unsafe_allow_html=True,
    )

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown('<div class="section-kicker">Duplicate pairs by priority</div>', unsafe_allow_html=True)
        if pairs.empty:
            st.caption("No candidate pairs at the current thresholds.")
        else:
            counts = pairs["LIKELIHOOD"].value_counts().reindex(["HIGH", "MEDIUM", "LOW"], fill_value=0)
            st.altair_chart(
                priority_bars(
                    pd.DataFrame({"PRIORITY": counts.index, "COUNT": counts.values}),
                    t("Pairs"),
                    {level: t(level) for level in ("HIGH", "MEDIUM", "LOW")},
                ),
                width="stretch",
            )
        st.markdown('<div class="section-kicker">Quality findings by rule</div>', unsafe_allow_html=True)
        if scan.quality_findings.empty:
            st.caption("No quality findings with the current rules.")
        else:
            rules = scan.quality_findings["RULE_CODE"].value_counts()
            frame = pd.DataFrame(
                {"RULE": [t(code.replace("_", " ").title().replace("Iban", "IBAN")) for code in rules.index], "COUNT": rules.values}
            )
            st.altair_chart(horizontal_bars(frame, "RULE", "COUNT", t("Findings")), width="stretch")
    with right:
        st.markdown('<div class="section-kicker">Field completeness</div>', unsafe_allow_html=True)
        completeness = scan.completeness[scan.completeness["FIELD"].ne("SUPPLIER_ID")].sort_values(["COMPLETENESS", "FIELD"])
        lowest = completeness.head(10)
        if not lowest.empty:
            st.altair_chart(
                horizontal_bars(
                    lowest.assign(LABEL=lowest["LABEL"].map(t)),
                    "LABEL",
                    "COMPLETENESS",
                    t("% of suppliers with a value"),
                    percent=True,
                    max_value=100,
                    sort="x",
                ),
                width="stretch",
            )
            complete = int(completeness["COMPLETENESS"].ge(100).sum())
            if len(completeness) > len(lowest):
                st.caption(
                    t(
                        "Showing the {shown} least complete of {total} mapped fields; {complete} fields are 100% complete.",
                        shown=len(lowest),
                        total=len(completeness),
                        complete=complete,
                    )
                )
        if scan.absent_fields:
            st.caption(t("Not provided by this file: ") + ", ".join(t(FIELD_BY_NAME[name].label) for name in sorted(scan.absent_fields)))

    st.markdown('<div class="section-kicker">Where to start</div>', unsafe_allow_html=True)
    if scan.clusters.empty:
        st.caption("No duplicate clusters at the selected priority. Check the review queue for lower-priority pairs.")
    else:
        top = scan.clusters.head(5)
        st.dataframe(
            pd.DataFrame(
                {
                    "Cluster": top["CLUSTER_ID"],
                    "Priority": top["TOP_LIKELIHOOD"].map(t),
                    "Suppliers": top["SIZE"],
                    "Score": top["MAX_SCORE"],
                    "Names": top["NAMES"],
                    "Suggested record to keep": top["SURVIVOR_ID"] + " · " + top["SURVIVOR_NAME"],
                    "Shared signals": top["SIGNALS"].map(t.sentence),
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.button("Open duplicate clusters →", key="go_clusters", on_click=_go, args=("Clusters",))

    if not pairs.empty and has_country:
        st.markdown('<div class="section-kicker">Countries with the most duplicate pairs</div>', unsafe_allow_html=True)
        countries = pairs[pairs["COUNTRY_CODE"].astype(str).str.strip().ne("")]["COUNTRY_CODE"].value_counts().head(10)
        if len(countries):
            st.altair_chart(
                horizontal_bars(
                    pd.DataFrame({"COUNTRY": countries.index, "PAIRS": countries.values}), "COUNTRY", "PAIRS", t("Duplicate pairs")
                ),
                width="stretch",
            )

    st.markdown('<div class="section-kicker">Export</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    report_scan, report_dataset, report_source, report_suppliers = scan, dataset_id, source_name, suppliers
    c1.download_button(
        "Download Excel report",
        lambda: build_excel_report(
            report_scan,
            _store().history(report_dataset),
            report_source,
            action_plan(report_scan.queue, _store().latest(report_dataset), report_suppliers),
        ),
        "supplier_integrity_report.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_report",
        type="primary",
        width="stretch",
    )
    full_queue = queue.copy()
    c2.download_button(
        "Download full queue (CSV)",
        lambda: csv_text(full_queue),
        "supplier_review_queue.csv",
        "text/csv",
        key="download_full_queue",
        width="stretch",
    )
    st.caption("The report has sheets for the summary, clusters, pairs, quality findings, field completeness and your decisions.")


# ================================================================= QUEUE
def _finding_label(item: dict[str, Any]) -> str:
    if item["TYPE"] == "DUPLICATE":
        return f"{item['SUPPLIER_ID']} → {item['CANDIDATE_ID']} · {item['SUPPLIER_NAME']} / {item['CANDIDATE_NAME']}"
    return f"{item['SUPPLIER_ID']} · {item['FIELD']} · {t.sentence(item['SUMMARY'])}"


def render_queue() -> None:
    st.subheader("Which suppliers need attention?")
    st.caption("Every finding comes from an explicit rule and has a suggested next action. The scan is plain Python — no AI requests.")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1.4])
    kind = c1.selectbox(
        "Finding type",
        ["All", "DUPLICATE", "DATA_QUALITY"],
        key="queue_type",
        format_func=lambda v: {"All": "All", "DUPLICATE": "Duplicates", "DATA_QUALITY": "Data quality"}[v],
    )
    priority = c2.selectbox("Priority", ["All", "HIGH", "MEDIUM", "LOW"], key="queue_priority")
    review = c3.selectbox("Review status", ["All", "Unreviewed", "Follow-up needed", "Decision recorded"], key="queue_status")
    search = c4.text_input("Search supplier ID or name", key="queue_search")
    filtered = queue
    if kind != "All":
        filtered = filtered[filtered["TYPE"].eq(kind)]
    if priority != "All":
        filtered = filtered[filtered["PRIORITY"].eq(priority)]
    if review == "Unreviewed":
        filtered = filtered[filtered["REVIEW_STATUS"].eq("UNREVIEWED")]
    elif review == "Follow-up needed":
        filtered = filtered[filtered["REVIEW_STATUS"].isin(["NEEDS_INVESTIGATION", "FIX_REQUIRED"])]
    elif review == "Decision recorded":
        filtered = filtered[filtered["REVIEW_STATUS"].ne("UNREVIEWED")]
    if search:
        mask = (
            filtered[["SUPPLIER_ID", "SUPPLIER_NAME", "CANDIDATE_ID", "CANDIDATE_NAME"]]
            .astype(str)
            .apply(lambda col: col.str.contains(search, case=False, regex=False))
            .any(axis=1)
        )
        filtered = filtered[mask]
    st.caption(
        t(
            "{shown} of {total} findings · {pairs} duplicate pairs · {quality} quality findings",
            shown=f"{len(filtered):,}",
            total=f"{len(queue):,}",
            pairs=f"{len(scan.duplicate_pairs):,}",
            quality=f"{len(scan.quality_findings):,}",
        )
    )
    if filtered.empty:
        st.info(
            "No findings match these filters. Clear the filters to see other findings; no findings does not prove the data is error-free."
        )
        return
    display = pd.DataFrame(
        {
            "Priority": filtered["PRIORITY"].map(t),
            "Finding": filtered["TYPE"].map({"DUPLICATE": t("Duplicate"), "DATA_QUALITY": t("Data quality")}),
            "Supplier": filtered["SUPPLIER_ID"] + " · " + filtered["SUPPLIER_NAME"],
            "Candidate / field": (filtered["CANDIDATE_ID"] + " · " + filtered["CANDIDATE_NAME"]).where(
                filtered["TYPE"].eq("DUPLICATE"), filtered["FIELD"]
            ),
            "Score": filtered["SCORE"],
            "Evidence": filtered["SUMMARY"].map(t.sentence),
            "Review": filtered["REVIEW_STATUS"].map(lambda value: t(_label(value))),
            "Earlier file": filtered["FINDING_ID"].map(lambda key: t(_label(earlier[key]["decision"])) if key in earlier else ""),
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=min(420, 38 + 35 * len(display)),
        column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f")},
    )
    st.download_button("Download filtered queue (CSV)", csv_text(filtered), "supplier_review_queue.csv", "text/csv", key="download_queue")

    findings_by_id = filtered.set_index("FINDING_ID").to_dict("index")
    selected = st.selectbox(
        "Open a finding", filtered["FINDING_ID"].tolist(), format_func=lambda key: _finding_label(findings_by_id[key]), key="queue_finding"
    )
    item = filtered[filtered.FINDING_ID.eq(selected)].iloc[0].to_dict()
    st.markdown('<div class="section-kicker">Finding detail</div>', unsafe_allow_html=True)
    if item["TYPE"] == "DUPLICATE":
        st.markdown(
            t("Selected pair:") + f" {item['SUPPLIER_ID']} · {item['SUPPLIER_NAME']} → {item['CANDIDATE_ID']} · {item['CANDIDATE_NAME']}"
        )
        st.markdown(
            f"{ui.priority_chip(item['PRIORITY'], t(item['PRIORITY']))} &nbsp; {t('rule score')} **{item['SCORE']:.1f}** · {ui.safe(t.sentence(item['SUMMARY']))}",
            unsafe_allow_html=True,
        )
        left, right = _records_by_id(suppliers, [item["SUPPLIER_ID"], item["CANDIDATE_ID"]])
        st.markdown(
            ui.legend() + ui.compare_table(compare_records(left, right, mask_sensitive), item["SUPPLIER_ID"], item["CANDIDATE_ID"]),
            unsafe_allow_html=True,
        )
        st.caption(t.sentence(item["ACTION"]) + " " + t("Rule scores prioritise review; they are not probabilities."))
        active = st.session_state.get("investigation_session")
        if active and active.paused_for_review:
            st.info("Finish the current investigation or start a new case in the Investigation view before opening another finding.")
        st.button(
            "Investigate this pair",
            key="open_finding",
            type="primary",
            on_click=_open_investigation,
            args=(item["SUPPLIER_ID"], item["CANDIDATE_ID"]),
            disabled=bool(active and active.paused_for_review),
        )
    else:
        st.markdown(
            f"{ui.priority_chip(item['PRIORITY'], t(item['PRIORITY']))} &nbsp; **{ui.safe(item['SUPPLIER_ID'])} · {ui.safe(item['SUPPLIER_NAME'])}** — "
            f"{ui.safe(t.sentence(item['SUMMARY']))}",
            unsafe_allow_html=True,
        )
        st.write(t.sentence(item["ACTION"]))
        st.caption(
            t("Rule {code}:", code=item["RULE_CODE"])
            + " "
            + t(RULE_DESCRIPTIONS.get(item["RULE_CODE"], ""))
            + " "
            + t("Quality findings are advisory; recording an action does not change the source file.")
        )
        with st.form("quality_review", clear_on_submit=False, border=False):
            options = sorted(QUALITY_DECISIONS)
            decision = st.selectbox(
                "Quality action", options, index=options.index("NEEDS_INVESTIGATION"), key="dq_decision", format_func=_label
            )
            reviewer = st.text_input("Reviewer name or initials", key="dq_reviewer")
            notes = st.text_area("Quality review notes", key="dq_notes")
            submitted = st.form_submit_button("Save quality review", type="primary")
        if submitted:
            try:
                store.record(dataset_id, selected, "DATA_QUALITY", decision, reviewer, notes, json.dumps(item, default=str))
                st.success("Quality review saved. Source data remains unchanged.")
                st.rerun()
            except (ValueError, OSError, DatabaseError) as error:
                st.error(str(error))


# ================================================================= CLUSTERS
def render_clusters() -> None:
    st.subheader("Duplicate clusters")
    st.caption(
        "Suppliers linked by duplicate pairs form a cluster (A ~ B and B ~ C put all three together). "
        "A record to keep is suggested from activity, status and completeness — the decision and any merge stay with you and your ERP."
    )
    clusters = scan.clusters
    if clusters.empty:
        st.info("No clusters at the selected priority. Lower the thresholds or include medium pairs in the sidebar.")
        return
    pair_ids = {cluster_id: [] for cluster_id in clusters["CLUSTER_ID"]}
    for row in queue[queue["CLUSTER_ID"].ne("")].itertuples(index=False):
        pair_ids.setdefault(row.CLUSTER_ID, []).append(row.FINDING_ID)
    reviewed = {cid: sum(1 for fid in ids if fid in latest) for cid, ids in pair_ids.items()}
    table = pd.DataFrame(
        {
            "Cluster": clusters["CLUSTER_ID"],
            "Priority": clusters["TOP_LIKELIHOOD"].map(t),
            "Suppliers": clusters["SIZE"],
            "Score": clusters["MAX_SCORE"],
            "Country": clusters["COUNTRY_CODE"],
            "Names": clusters["NAMES"],
            "Keep (suggested)": clusters["SURVIVOR_ID"],
            "Signals": clusters["SIGNALS"].map(t.sentence),
            "Pairs reviewed": [f"{reviewed.get(cid, 0)}/{len(pair_ids.get(cid, []))}" for cid in clusters["CLUSTER_ID"]],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch", height=min(380, 38 + 35 * len(table)))
    st.download_button(
        "Download clusters (CSV)", csv_text(scan.cluster_members), "duplicate_cluster_members.csv", "text/csv", key="download_clusters"
    )

    by_id = clusters.set_index("CLUSTER_ID").to_dict("index")
    cluster_id = st.selectbox(
        "Open a cluster",
        clusters["CLUSTER_ID"].tolist(),
        key="cluster_pick",
        format_func=lambda cid: f"{cid} · {by_id[cid]['SIZE']} {t('suppliers')} · {by_id[cid]['NAMES'][:70]}",
    )
    info = by_id[cluster_id]
    members = scan.cluster_members[scan.cluster_members["CLUSTER_ID"].eq(cluster_id)]
    ids = members["SUPPLIER_ID"].tolist()  # survivor first
    st.markdown(
        f'<div class="survivor"><b>Suggested record to keep: {ui.safe(info["SURVIVOR_ID"])} · {ui.safe(info["SURVIVOR_NAME"])}</b>'
        f'<br><span style="color:var(--muted)">{ui.safe(info["SURVIVOR_REASON"])}</span></div>',
        unsafe_allow_html=True,
    )
    records = _records_by_id(suppliers, ids)
    titles = [f"★ {ids[0]} ({t('keep')})"] + ids[1:]
    st.markdown(ui.legend() + ui.group_table(compare_group(records, 0, mask_sensitive), titles), unsafe_allow_html=True)
    links = scan.duplicate_pairs[scan.duplicate_pairs["SUPPLIER_ID_A"].isin(ids) & scan.duplicate_pairs["SUPPLIER_ID_B"].isin(ids)]
    with st.expander(t("{count} pair links inside this cluster", count=len(links))):
        st.dataframe(
            links[["SUPPLIER_ID_A", "SUPPLIER_ID_B", "LIKELIHOOD", "DUPLICATE_SCORE", "EVIDENCE"]].rename(
                columns={
                    "SUPPLIER_ID_A": "Supplier A",
                    "SUPPLIER_ID_B": "Supplier B",
                    "LIKELIHOOD": "Priority",
                    "DUPLICATE_SCORE": "Score",
                    "EVIDENCE": "Evidence",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    st.markdown('<div class="section-kicker">Record a decision for every pair in this cluster</div>', unsafe_allow_html=True)
    with st.form("cluster_review", border=False):
        options = sorted(ALLOWED_REVIEW_DECISIONS)
        decision = st.radio(
            "Decision", options, index=options.index("NEEDS_INVESTIGATION"), horizontal=True, format_func=_label, key="cluster_decision"
        )
        reviewer = st.text_input("Reviewer name or initials", key="cluster_reviewer")
        notes = st.text_area("Notes", key="cluster_notes", help="For example: which record should survive and why.")
        submitted = st.form_submit_button("Save cluster decision", type="primary")
    if submitted:
        try:
            case = json.dumps({"cluster": info | {"CLUSTER_ID": cluster_id}, "members": ids}, default=str)
            for link in links.itertuples(index=False):
                fid = finding_id("DUP", *sorted((str(link.SUPPLIER_ID_A), str(link.SUPPLIER_ID_B))))
                store.record(dataset_id, fid, "DUPLICATE", decision, reviewer, notes, case)
            st.success(
                t("Saved “{decision}” for {count} pairs. Source data remains unchanged.", decision=t(_label(decision)), count=len(links))
            )
            st.rerun()
        except (ValueError, OSError, DatabaseError) as error:
            st.error(str(error))
    st.button(
        "Investigate the suggested record with the agent",
        key="cluster_investigate",
        on_click=_open_investigation,
        args=(ids[0], ids[1] if len(ids) > 1 else None),
    )


# ================================================================= WHAT'S NEW
@st.cache_data(show_spinner=False, max_entries=4)
def _scan_previous(contents: bytes, mapping_json: str, scan_key_json: str, salt: str) -> dict:
    """Scan an earlier file with the current mapping and rules; return its snapshot."""
    previous_raw = read_supplier_table(contents)
    previous_mapping = json.loads(mapping_json)
    usable = {key: (value if value in previous_raw.columns else None) for key, value in previous_mapping.items()}
    if missing_required(usable):
        usable = suggest_mapping(previous_raw.columns)
    previous = validate_supplier_master(apply_mapping(previous_raw, usable))
    result = scan_suppliers(previous, quality_config, detection_config, cluster_level)
    return make_snapshot(result, previous, "earlier file", salt)


def render_changes() -> None:
    st.subheader("What changed since the earlier file?")
    st.caption(
        "Compare this scan with an earlier version of the supplier master: new and resolved findings, added and removed "
        "suppliers, and records whose key fields changed. Earlier scans are kept as fingerprints only — names and hashed "
        "values, never the bank or tax numbers themselves."
    )
    salt = store.salt()
    current = make_snapshot(scan, suppliers, source_name, salt)
    baselines = store.snapshots(exclude_dataset=dataset_id)
    options = ["upload"] + [str(item["id"]) for item in baselines]
    labels = {"upload": "Upload the earlier file"} | {
        str(
            item["id"]
        ): f"{item['created_at'][:16].replace('T', ' ')} · {item['source_name']} · {item['supplier_count']:,} {t('suppliers')}"
        for item in baselines
    }
    if source == "Sample data":
        options.insert(0, "sample")
        labels["sample"] = "Sample data from the previous quarter"
    choice = st.selectbox("Compare with", options, format_func=labels.get, key="baseline_choice")
    baseline = None
    try:
        if choice == "sample":
            baseline = _scan_previous(PREVIOUS_SAMPLE.read_bytes(), json.dumps(mapping), repr(scan_key), salt)
        elif choice == "upload":
            earlier_file = st.file_uploader("Earlier file", type=["xlsx", "xlsm", "csv", "tsv", "txt"], key="baseline_upload")
            if earlier_file is not None:
                baseline = _scan_previous(earlier_file.getvalue(), json.dumps(mapping), repr(scan_key), salt)
        else:
            baseline = store.snapshot(int(choice))
    except Exception as error:  # noqa: BLE001 - shown to the user
        st.error(t("The earlier file could not be compared: {error}", error=error))
        return
    if baseline is None:
        st.info("Choose an earlier scan above, or upload last month's export. Every file you scan is remembered for this comparison.")
        return
    changes = compare_snapshots(baseline, current)
    summary = change_summary(changes)
    st.markdown(
        ui.kpi_tiles(
            [
                (t("New findings"), f"{summary['new_findings']:,}", t("duplicates and quality issues")),
                (t("Resolved"), f"{summary['resolved_findings']:,}", t("no longer found")),
                (
                    t("Changed suppliers"),
                    f"{summary['changed_suppliers']:,}",
                    t("{count} bank, tax or email changes", count=f"{summary['sensitive_changes']:,}"),
                ),
                (t("Added"), f"{summary['new_suppliers']:,}", t("new supplier records")),
                (t("Removed"), f"{summary['removed_suppliers']:,}", t("no longer in the file")),
            ]
        ),
        unsafe_allow_html=True,
    )
    bank_changes = changes[changes["DETAIL"].str.contains("Bank details changed", regex=False)] if not changes.empty else changes
    if len(bank_changes):
        st.warning(
            t(
                "{count} supplier(s) changed bank details. Changed bank accounts are a common route for payment fraud: "
                "confirm each change with the supplier through a contact you already know before the next payment run.",
                count=len(bank_changes),
            )
        )
    if changes.empty:
        st.success("No differences between the two scans.")
        return
    kinds = {
        "All": "All changes",
        "NEW_FINDING": "New findings",
        "CHANGED_SUPPLIER": "Changed suppliers",
        "RESOLVED_FINDING": "Resolved findings",
        "NEW_SUPPLIER": "Added suppliers",
        "REMOVED_SUPPLIER": "Removed suppliers",
    }
    kind = st.selectbox("Show", list(kinds), format_func=kinds.get, key="change_filter")
    shown = changes if kind == "All" else changes[changes["CHANGE"].eq(kind)]
    st.dataframe(
        shown.drop(columns=["FINDING_ID"])
        .assign(
            CHANGE=shown["CHANGE"].map(lambda value: t(kinds[value])),
            DETAIL=shown["DETAIL"].map(t.sentence),
            PRIORITY=shown["PRIORITY"].map(t),
        )
        .rename(
            columns={"CHANGE": "Change", "PRIORITY": "Priority", "SUPPLIER_ID": "Supplier", "SUPPLIER_NAME": "Name", "DETAIL": "Detail"}
        ),
        hide_index=True,
        width="stretch",
    )
    st.download_button("Download changes (CSV)", csv_text(changes), "supplier_changes.csv", "text/csv", key="download_changes")


# ================================================================= CHECK A SUPPLIER
def render_check() -> None:
    st.subheader("Is this supplier already in the master?")
    st.caption(
        "Run this before creating a supplier. Enter what you know — a name and one identifier are usually enough. "
        "The entry is compared with the loaded file using the same rules as the scan; nothing is saved."
    )
    with st.form("new_supplier_check", border=False):
        c1, c2, c3 = st.columns([2, 1, 1])
        name = c1.text_input("Supplier name", key="chk_name")
        country = c2.text_input("Country code", key="chk_country", max_chars=3, placeholder="GB")
        tax = c3.text_input("Tax / VAT number", key="chk_tax")
        c4, c5, c6 = st.columns([2, 1, 1])
        address = c4.text_input("Street address", key="chk_address")
        city = c5.text_input("City", key="chk_city")
        postal = c6.text_input("Postal code", key="chk_postal")
        c7, c8, c9, c10 = st.columns([2, 1, 1.4, 1])
        iban = c7.text_input("IBAN / bank account", key="chk_bank")
        registration = c8.text_input("Registration no.", key="chk_registration")
        email = c9.text_input("Email", key="chk_email")
        phone = c10.text_input("Phone", key="chk_phone")
        submitted = st.form_submit_button("Check", type="primary")
    if not submitted:
        return
    record = {
        "SUPPLIER_NAME": name,
        "COUNTRY_CODE": country.strip().upper(),
        "TAX_ID": tax,
        "ADDRESS_1": address,
        "CITY": city,
        "POSTAL_CODE": postal,
        "BANK_ACCOUNT": iban,
        "BANK_COUNTRY": country.strip().upper() if iban else "",
        "ASSOCIATION_NO": registration,
        "EMAIL": email,
        "PHONE": phone,
    }
    problems = validate_new_supplier(record)
    matches = find_existing(suppliers, record, detection_config)
    outcome = verdict(matches)
    if outcome == "LIKELY_EXISTS":
        top = matches.iloc[0]
        st.error(
            t(
                "Likely already exists: {supplier} ({evidence}). Use or update that record instead.",
                supplier=f"{top['SUPPLIER_ID']} · {top['SUPPLIER_NAME']}",
                evidence=t.sentence(top["EVIDENCE"]),
            )
        )
    elif outcome == "POSSIBLE_MATCH":
        st.warning(t("{count} possible match(es). Review them before creating a new record.", count=len(matches)))
    else:
        st.success("No existing supplier matches these details.")
    for problem in problems:
        st.warning(t.sentence(problem))
    if not matches.empty:
        st.dataframe(
            matches.drop(columns=["NAME_SIMILARITY", "SHARED_IDENTIFIER"])
            .assign(EVIDENCE=matches["EVIDENCE"].map(t.sentence), LIKELIHOOD=matches["LIKELIHOOD"].map(t))
            .rename(
                columns={
                    "SUPPLIER_ID": "Supplier",
                    "SUPPLIER_NAME": "Name",
                    "COUNTRY_CODE": "Country",
                    "ACTIVE_STATUS": "Status",
                    "DUPLICATE_SCORE": "Score",
                    "LIKELIHOOD": "Priority",
                    "EVIDENCE": "Evidence",
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f")},
        )


# ================================================================= INVESTIGATION
def _candidate_table(state: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Candidate": item.get("SUPPLIER_ID_B"),
                "Supplier name": item.get("SUPPLIER_NAME_B"),
                "Priority": item.get("LIKELIHOOD"),
                "Rule score": item.get("DUPLICATE_SCORE"),
                "Name %": item.get("NAME_SIMILARITY"),
                "Address %": item.get("ADDRESS_SIMILARITY"),
                "Semantic %": item.get("SEMANTIC_SIMILARITY"),
            }
            for item in state.get("candidates", [])
        ]
    )


def _save_case(session: InvestigationSession) -> None:
    state = session.final_state or {}
    candidate = state.get("reviewed_candidate_id")
    identity = finding_id("DUP", *sorted((state["supplier_id"], candidate))) if candidate else finding_id("CASE", state["supplier_id"])
    store.record(
        dataset_id, identity, "DUPLICATE", state["review_decision"], state["reviewer"], state.get("review_notes", ""), session.export_json()
    )
    st.session_state.saved_case_thread = session.thread_id


def _render_case(session: InvestigationSession) -> None:
    state = session.current_state or {}
    supplier = state.get("supplier") or {}
    activity = state.get("supplier_activity") or {}
    st.markdown(ui.route(5 if session.paused_for_review else 6), unsafe_allow_html=True)
    if state.get("status") == "ERROR":
        for error in state.get("errors", ["The investigation could not be completed."]):
            st.error(error)
        return
    for warning in state.get("warnings", []):
        st.warning(warning)
    quality = state.get("quality_findings", [])
    if quality:
        with st.expander(t("{count} data-quality findings for this supplier", count=len(quality))):
            findings = pd.DataFrame(quality)[["FIELD", "PRIORITY", "SUMMARY", "ACTION"]]
            for column in ("SUMMARY", "ACTION"):
                findings[column] = findings[column].map(t.sentence)
            st.dataframe(findings, hide_index=True, width="stretch")
            st.caption("Record quality actions in the review queue; a duplicate decision does not resolve these findings.")

    st.subheader(ui.text(supplier.get("SUPPLIER_NAME")))
    st.markdown(
        f"""<div class="record-strip">
        <div class="record-cell"><span class="record-label">Supplier ID</span><span class="record-value">{ui.safe(supplier.get("SUPPLIER_ID"))}</span></div>
        <div class="record-cell"><span class="record-label">Country</span><span class="record-value">{ui.safe(supplier.get("COUNTRY_CODE"))}</span></div>
        <div class="record-cell"><span class="record-label">Company / site</span><span class="record-value">{ui.safe(supplier.get("COMPANY"))} / {ui.safe(supplier.get("SITE"))}</span></div>
        <div class="record-cell"><span class="record-label">Status</span><span class="record-value">{ui.safe(supplier.get("ACTIVE_STATUS"))}</span></div>
        <div class="record-cell"><span class="record-label">12m activity</span><span class="record-value">{ui.safe(activity.get("PO_COUNT_12M"))} POs</span></div>
        </div>""",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.5, 1], gap="large")
    with left:
        candidates = state.get("candidates", [])
        st.subheader(t("{count} records require comparison", count=len(candidates)))
        table = _candidate_table(state)
        if table.empty:
            st.info("No candidate passed the current deterministic or semantic thresholds.")
        else:
            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                column_config={
                    "Rule score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Semantic %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                },
            )
            selected_id = st.selectbox("Compare side by side", options=table["Candidate"].tolist(), key="candidate_id")
            evidence = next(item for item in state.get("evidence", []) if item.get("SUPPLIER_ID_B") == selected_id)
            st.caption(
                "Evidence: "
                + (evidence.get("EVIDENCE") or "no supporting signal recorded")
                + ". Rule scores prioritise review; they are not probabilities. Optional semantic similarity does not alter them."
            )
            pair = _records_by_id(suppliers, [str(supplier.get("SUPPLIER_ID")), str(selected_id)])
            if len(pair) == 2:
                st.markdown(
                    ui.compare_table(compare_records(pair[0], pair[1], mask_sensitive), pair[0]["SUPPLIER_ID"], pair[1]["SUPPLIER_ID"]),
                    unsafe_allow_html=True,
                )

        st.subheader("Evidence explanation")
        st.markdown(f'<div class="analysis-box">{ui.safe(state.get("ai_analysis"))}</div>', unsafe_allow_html=True)
        mode = str(state.get("analysis_mode", ""))
        explanation = (
            "Offline rules (Gemini fallback)"
            if mode == "DETERMINISTIC_FALLBACK"
            else mode.replace("GEMINI:", "Gemini · ")
            if mode.startswith("GEMINI:")
            else "Offline rules"
        )
        st.caption(t("Explanation: {source}", source=t(explanation)))

    with right:
        st.subheader("Data Steward decision")
        st.write(ui.text(state.get("recommendation")))
        if session.paused_for_review:
            st.warning("Awaiting human review — the agent cannot merge or delete supplier records.")
            candidate_ids = [str(item["SUPPLIER_ID_B"]) for item in state.get("candidates", [])]
            selected_candidate = (
                st.selectbox("Candidate this decision applies to", candidate_ids, key="review_candidate_id") if candidate_ids else None
            )
            decisions = sorted(ALLOWED_REVIEW_DECISIONS if candidate_ids else ALLOWED_REVIEW_DECISIONS - {"CONFIRM_DUPLICATE"})
            reviewer = st.text_input("Reviewer name or initials", key="reviewer")
            notes = st.text_area(
                "Decision notes",
                key="review_notes",
                help="Why you reached this conclusion. Do not enter credentials or sensitive identifiers.",
            )
            decision = st.radio(
                "Record your decision",
                options=decisions,
                index=decisions.index("NEEDS_INVESTIGATION"),
                format_func=lambda value: value.replace("_", " ").title(),
                key="review_decision",
            )
            if st.button("Submit steward decision", type="primary", key="submit_decision", width="stretch"):
                if not reviewer.strip():
                    st.error("Enter a reviewer name or initials before submitting.")
                else:
                    try:
                        session.submit_decision(decision, selected_candidate, reviewer, notes)
                        _save_case(session)
                        st.rerun()
                    except (ValueError, OSError, DatabaseError) as error:
                        st.error(t("The decision could not be saved: {error}. You can retry or download the case record.", error=error))
        else:
            decision = state.get("review_decision")
            st.success(t("Human review complete — {decision}", decision=t(_label(ui.text(decision)))))
            st.caption(
                t(
                    "Applies to candidate: {candidate} · reviewer: {reviewer}",
                    candidate=ui.text(state.get("reviewed_candidate_id"), t("supplier-level follow-up")),
                    reviewer=ui.text(state.get("reviewer")),
                )
            )
            if st.session_state.get("saved_case_thread") != session.thread_id:
                st.warning("This completed case has not been saved to local review history. Download it or retry saving.")
                if st.button("Retry saving review", key="retry_save"):
                    try:
                        _save_case(session)
                        st.rerun()
                    except (OSError, DatabaseError):
                        st.error("Local review history is unavailable. Download the case to keep your decision.")
            st.download_button(
                "Download case record",
                data=session.export_json(),
                file_name=f"investigation_{state.get('supplier_id', 'case')}.json",
                mime="application/json",
                key="download_case",
                width="stretch",
            )

        st.subheader("Retrieved guidance")
        for policy in state.get("policy_context", []):
            retrieval = (
                "Keyword retrieval"
                if policy.get("retrieval_mode") == "KEYWORD"
                else t("Keyword + semantic retrieval · similarity {value}%", value=ui.text(policy.get("semantic_similarity")))
            )
            st.markdown(
                f'<div class="policy-item"><div class="policy-cite">{ui.safe(policy.get("citation"))}</div>'
                f'<div>{ui.safe(policy.get("text"))}</div><div class="policy-meta">{ui.safe(retrieval)}</div></div>',
                unsafe_allow_html=True,
            )

    with st.expander("How this screen maps to the architecture"):
        st.markdown("""
1. **LangGraph** runs the fixed investigation stages and pauses at the human checkpoint.
2. **Controlled tools** read the table and calculate exact, fuzzy and (optional) semantic evidence.
3. **LlamaIndex** retrieves relevant policy passages with citations.
4. **The analysis provider** (offline rules or Gemini) explains existing evidence but cannot change scores or decide.
5. **The Data Steward** submits the final decision and can download the audit record.
""")


def render_investigation() -> None:
    if "investigation_session" in st.session_state:
        if st.button("Start a new case", key="new_case"):
            del st.session_state.investigation_session
            st.session_state.review_notes = ""
            st.rerun()
        _render_case(st.session_state.investigation_session)
        return
    st.markdown(ui.route(1), unsafe_allow_html=True)
    form_col, context_col = st.columns([1.45, 1], gap="large")
    with form_col:
        st.subheader("Open a supplier case")
        ids = suppliers["SUPPLIER_ID"].tolist()
        names = dict(zip(suppliers["SUPPLIER_ID"], suppliers["SUPPLIER_NAME"], strict=True))
        pick_key = f"supplier_pick_{dataset_id[:12]}"
        pending = st.session_state.pop("pending_supplier", None)
        if pending in names:
            st.session_state[pick_key] = pending
        elif pick_key not in st.session_state:
            st.session_state[pick_key] = DEMO_SUPPLIER if DEMO_SUPPLIER in names else ids[0]
        supplier_id = st.selectbox(
            "Supplier", ids, key=pick_key, format_func=lambda key: f"{key} · {names[key]}", help="Type to search by ID or name."
        )
        st.session_state.supplier_id = supplier_id
        provider_options = ["Deterministic (offline)"]
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider_options.append("Gemini (AI explanation)")
        provider_label = st.selectbox(
            "Analysis provider",
            options=provider_options,
            key="analysis_provider",
            help="The provider explains evidence only. It cannot change scores or decide the case.",
        )
        semantic_enabled = st.checkbox(
            "Enable local semantic embeddings",
            value=False,
            key="semantic_enabled",
            help="Optional; needs the 'semantic' extra and downloads a small model on first use.",
        )
        if len(provider_options) == 1:
            st.caption("Gemini becomes available when GEMINI_API_KEY is set before starting the app. The default needs no key.")
        if st.button("Start investigation", type="primary", key="start_investigation", width="stretch"):
            try:
                session = InvestigationSession(
                    suppliers,
                    analysis_provider="gemini" if provider_label.startswith("Gemini") else "deterministic",
                    semantic_enabled=semantic_enabled,
                    detection_config=detection_config,
                )
                with st.spinner("Running the controlled investigation route…"):
                    session.start(supplier_id, st.session_state.get("pending_candidate"))
                st.session_state.investigation_session = session
                candidate_ids = {str(item["SUPPLIER_ID_B"]) for item in (session.current_state or {}).get("candidates", [])}
                pending = st.session_state.pop("pending_candidate", None)
                if pending in candidate_ids:
                    st.session_state.review_candidate_id = pending
                    st.session_state.candidate_id = pending
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - shown to the user
                st.error(t("Investigation could not start: {error}", error=exc))
    with context_col:
        st.subheader("What the agent will do")
        st.markdown("""
1. **Load** the selected supplier and its activity
2. **Search** exact, fuzzy and optional semantic candidates
3. **Compare** deterministic evidence without changing scores
4. **Retrieve** policy passages relevant to this case
5. **Pause** until a Data Steward records the decision
""")
        if source == "Sample data":
            st.caption(
                t(
                    "Demo case: {supplier} has exact matches. Enable embeddings to explore additional semantic candidates.",
                    supplier=DEMO_SUPPLIER,
                )
            )


# ================================================================= HISTORY
def render_history() -> None:
    st.subheader("Recorded decisions")
    history = store.history(dataset_id)
    st.caption(
        "Local, append-only history for this dataset (a changed file gets its own history). "
        "Reviewer names are self-reported; this is not an authenticated audit system."
    )
    if not history:
        st.info("No decisions recorded yet. Review a queue finding, a cluster, or complete an investigation to add one.")
        return
    table = pd.DataFrame(history).drop(columns="case_json")
    counts = table["decision"].value_counts()
    st.markdown(
        ui.kpi_tiles([(t(_label(name)), f"{count:,}", t("decisions")) for name, count in counts.head(5).items()]), unsafe_allow_html=True
    )
    st.dataframe(table, hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    c1.download_button(
        "Download review history (CSV)", csv_text(table), "review_history.csv", "text/csv", key="download_history", width="stretch"
    )
    c2.download_button(
        "Download review history (JSON)",
        json.dumps(history, indent=2),
        "review_history.json",
        "application/json",
        key="download_history_json",
        width="stretch",
    )
    st.markdown('<div class="section-kicker">Action plan for your ERP team</div>', unsafe_allow_html=True)
    plan = action_plan(scan.queue, latest, suppliers)
    if plan.empty:
        st.caption("Confirm duplicates (per pair or per cluster) to build a keep / block list here.")
    else:
        st.caption(
            t(
                "{count} records to block, grouped by the record to keep. The keep record follows the same rule as the "
                "suggestion (active, most orders and spend, most complete, oldest). Nothing has been changed in your data.",
                count=len(plan),
            )
        )
        st.dataframe(plan.drop(columns=["ACTION"]), hide_index=True, width="stretch")
        st.download_button(
            "Download action plan (CSV)", csv_text(plan), "supplier_action_plan.csv", "text/csv", key="download_actions", type="primary"
        )
    st.markdown('<div class="section-kicker">Saved records</div>', unsafe_allow_html=True)
    selected = st.selectbox(
        "Download a saved record",
        list(range(len(history))),
        format_func=lambda index: (
            f"{history[index]['reviewed_at'][:19]} · {t(_label(history[index]['decision']))} · {history[index]['finding_id']}"
        ),
    )
    st.download_button(
        "Download saved record (JSON)",
        history[selected]["case_json"] or "{}",
        "review_record.json",
        "application/json",
        key="download_saved",
    )


# ================================================================= GUIDE
def render_guide() -> None:
    st.subheader("How it works")
    st.markdown("""
**1. Load.** Any supplier/vendor export (Excel or CSV). Columns are mapped to a standard schema from common ERP names
(SAP `LIFNR`, `STCD1`, `NAME1`…, or plain names such as *Vendor No* or *VAT number*). Only **Supplier ID** and
**Supplier name** are required; every extra field improves matching.

**2. Scan.** Plain Python, no AI:
- *Exact signals* — same tax ID, registration number (within a country) or bank account (within a bank country).
  Placeholder values such as `N/A` or `0000` are ignored.
- *Fuzzy signals* — similar normalized names (legal suffixes removed) and addresses (abbreviations expanded).
- A transparent **rule score** (tax 25, registration 20, bank 20, name up to 20, address up to 15) sets the priority.
- **Quality rules** flag invalid IBANs, blank required fields, malformed codes, bank accounts without a bank country,
  invalid activity values and inactive suppliers with recent orders.

**3. Cluster.** Linked pairs become clusters and a record to keep is suggested (active, most orders, most spend, most complete, oldest).

**4. Review.** Compare records side by side, record decisions per finding or per cluster, and export an Excel report.
Confirmed duplicates become a keep / block **action plan** (Review history) for the team that maintains your ERP.
The **Investigation** view runs a LangGraph agent that gathers evidence through allow-listed read-only tools, retrieves
cited policy passages and pauses for your decision. Gemini is optional and only receives non-sensitive fields.

**What it will never do:** change, merge or delete your supplier records; send tax IDs or bank details to an AI service;
treat a score as proof of identity.
""")
    st.markdown('<div class="section-kicker">Quality rules</div>', unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame({"Rule": list(RULE_DESCRIPTIONS), "Meaning": list(RULE_DESCRIPTIONS.values())}), hide_index=True, width="stretch"
    )
    st.markdown('<div class="section-kicker">Fields</div>', unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Field": spec.name,
                    "Label": spec.label,
                    "Required": "yes" if spec.required else "",
                    "Used for matching": "yes" if spec.used_for_matching else "",
                    "Description": spec.description,
                }
                for spec in FIELDS
            ]
        ),
        hide_index=True,
        width="stretch",
    )


{
    "Overview": render_overview,
    "Review queue": render_queue,
    "Clusters": render_clusters,
    "What's new": render_changes,
    "Check a supplier": render_check,
    "Investigation": render_investigation,
    "Review history": render_history,
    "Guide": render_guide,
}[page]()

st.markdown(
    f'<div style="margin-top:3rem;color:var(--muted);font-size:.75rem;border-top:1px solid var(--line);padding-top:.6rem">'
    f"Supplier Integrity Desk v{__version__} · "
    + t("MIT licensed · advisory tool — decisions and merges remain with the Data Steward.")
    + "</div>",
    unsafe_allow_html=True,
)
