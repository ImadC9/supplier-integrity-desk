"""HTML fragments for the Streamlit interface.

Pure functions (no Streamlit import) so they are easy to test. Every value is
escaped; the only markup is produced here.
"""

from __future__ import annotations

from collections.abc import Iterable
from html import escape
from typing import Any

STATUS_LABEL = {
    "match": "Match",
    "similar": "Similar",
    "different": "Different",
    "missing": "Blank",
    "context": "",
    "reference": "Reference",
}
STATUS_SYMBOL = {"match": "●", "similar": "◐", "different": "○", "missing": "–", "context": "", "reference": "★"}


def text(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return fallback if value in {"", "nan", "NaT", "<NA>", "None"} else value


def safe(value: Any, fallback: str = "—") -> str:
    return escape(text(value, fallback))


def priority_chip(priority: str, label: str | None = None) -> str:
    """Coloured badge; the CSS class uses the English code, the text can be translated."""
    key = text(priority, "").lower()
    return f'<span class="chip chip-{escape(key)}">{escape(text(label if label is not None else priority))}</span>'


def kpi_tiles(items: Iterable[tuple[str, str, str]]) -> str:
    """items: (label, value, footnote)."""
    tiles = "".join(
        f'<div class="kpi"><span class="kpi-label">{escape(label)}</span>'
        f'<span class="kpi-value">{escape(value)}</span><span class="kpi-foot">{escape(foot)}</span></div>'
        for label, value, foot in items
    )
    return f'<div class="kpis">{tiles}</div>'


def compare_table(rows: list[dict], left_title: str, right_title: str) -> str:
    """Side-by-side table built from ``compare.compare_records`` rows."""
    if not rows:
        return '<div class="empty-note">No comparable fields.</div>'
    body = []
    for row in rows:
        status = row["STATUS"]
        similarity = "" if row["SIMILARITY"] is None or status in {"match", "missing"} else f" {row['SIMILARITY']:.0f}%"
        badge = (
            f'<span class="cmp-badge cmp-{status}">{STATUS_SYMBOL[status]} {STATUS_LABEL[status]}{similarity}</span>'
            if STATUS_LABEL[status]
            else ""
        )
        body.append(
            f'<tr class="row-{status}"><th scope="row">{escape(row["LABEL"])}</th>'
            f'<td>{safe(row["A"])}</td><td>{safe(row["B"])}</td><td class="cmp-status">{badge}</td></tr>'
        )
    return (
        '<div class="table-scroll"><table class="cmp"><thead><tr><th scope="col">Field</th>'
        f'<th scope="col">{escape(left_title)}</th><th scope="col">{escape(right_title)}</th>'
        '<th scope="col">Signal</th></tr></thead><tbody>' + "".join(body) + "</tbody></table></div>"
    )


def group_table(rows: list[dict], titles: list[str]) -> str:
    """Cluster comparison from ``compare.compare_group`` rows (first title = reference)."""
    if not rows:
        return '<div class="empty-note">No comparable fields.</div>'
    header = "".join(f'<th scope="col">{escape(title)}</th>' for title in titles)
    body = []
    for row in rows:
        cells = []
        for value, status in zip(row["VALUES"], row["STATUSES"]):
            symbol = STATUS_SYMBOL.get(status, "")
            marker = (
                f'<span class="cell-mark cmp-{status}" title="{escape(STATUS_LABEL.get(status, ""))}">{symbol}</span> '
                if symbol and status != "reference"
                else ""
            )
            cells.append(f'<td class="cell-{status}">{marker}{safe(value)}</td>')
        body.append(f'<tr><th scope="row">{escape(row["LABEL"])}</th>{"".join(cells)}</tr>')
    return (
        f'<div class="table-scroll"><table class="cmp cmp-group"><thead><tr><th scope="col">Field</th>{header}'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def route(active_stage: int) -> str:
    labels = ["Load record", "Find candidates", "Check evidence", "Retrieve policy", "Human review"]
    items = []
    for index, label in enumerate(labels, start=1):
        state = "done" if index < active_stage else "current" if index == active_stage else ""
        items.append(
            f'<div class="route-step {state}"><span class="route-dot"></span>'
            f'<span class="route-label">{label}</span><span class="route-number">0{index}</span></div>'
        )
    return '<div class="route">' + "".join(items) + "</div>"


def legend() -> str:
    return (
        '<div class="cmp-legend">'
        + "".join(
            f'<span class="cmp-badge cmp-{key}">{STATUS_SYMBOL[key]} {STATUS_LABEL[key]}</span>'
            for key in ("match", "similar", "different", "missing")
        )
        + "</div>"
    )
