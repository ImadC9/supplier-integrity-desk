"""Small Altair charts for the overview page (single hue + reserved priority colors)."""

from __future__ import annotations

import altair as alt
import pandas as pd

INK = "#102a43"
MUTED = "#5f7180"
GRID = "#dbe5e5"
BAR = "#146b8c"
# Status palette, validated for CVD separation; always shown with text labels.
PRIORITY_COLORS = {"HIGH": "#b8322a", "MEDIUM": "#b07a00", "LOW": "#1f78a8"}
PRIORITY_ORDER = ["HIGH", "MEDIUM", "LOW"]


def _base(chart: alt.Chart) -> alt.Chart:
    return (
        chart.properties(height=alt.Step(26))
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=MUTED,
            titleColor=MUTED,
            gridColor=GRID,
            domainColor=GRID,
            tickColor=GRID,
            labelFontSize=11,
            titleFontSize=11,
            labelFont="Inter, system-ui, sans-serif",
        )
        .configure(background="transparent")
    )


def horizontal_bars(
    frame: pd.DataFrame,
    category: str,
    value: str,
    value_title: str,
    percent: bool = False,
    color: str = BAR,
    max_value: float | None = None,
    sort: str = "-x",
) -> alt.Chart:
    """Sorted horizontal bars with direct value labels and a hover tooltip."""
    data = frame.copy()
    data["_label"] = data[value].map(lambda v: f"{v:.0f}%" if percent else f"{int(v):,}")
    top = max_value if max_value is not None else max(float(data[value].max() or 0), 1.0)
    scale = alt.Scale(domain=[0, top * 1.12], nice=False)  # room for the direct labels
    axis = alt.Axis(values=[0, 25, 50, 75, 100]) if percent else alt.Axis(tickCount=4)
    y = alt.Y(f"{category}:N", sort=sort, title=None, axis=alt.Axis(labelLimit=180))
    bars = (
        alt.Chart(data)
        .mark_bar(color=color, cornerRadiusEnd=4, size=16)
        .encode(
            x=alt.X(f"{value}:Q", title=value_title, scale=scale, axis=axis),
            y=y,
            tooltip=[
                alt.Tooltip(f"{category}:N", title="Item"),
                alt.Tooltip(f"{value}:Q", title=value_title, format=",.1f" if percent else ","),
            ],
        )
    )
    labels = alt.Chart(data).mark_text(align="left", dx=4, color=INK, fontSize=11).encode(x=f"{value}:Q", y=y, text="_label:N")
    return _base(bars + labels)


def priority_bars(frame: pd.DataFrame, title: str, labels: dict[str, str] | None = None) -> alt.Chart:
    """Counts per priority, colored with the reserved status palette and labelled.

    ``labels`` translates the axis text (e.g. {"HIGH": "ALTA"}) without changing colors.
    """
    data = frame.copy()
    labels = labels or {}
    order = [labels.get(level, level) for level in PRIORITY_ORDER]
    data["PRIORITY"] = data["PRIORITY"].map(lambda level: labels.get(level, level))
    data["_label"] = data["COUNT"].map(lambda v: f"{int(v):,}")
    y = alt.Y("PRIORITY:N", sort=order, title=None)
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4, size=16)
        .encode(
            x=alt.X(
                "COUNT:Q",
                title=title,
                axis=alt.Axis(tickCount=4),
                scale=alt.Scale(domain=[0, max(float(data["COUNT"].max() or 0), 1.0) * 1.12], nice=False),
            ),
            y=y,
            color=alt.Color("PRIORITY:N", scale=alt.Scale(domain=order, range=list(PRIORITY_COLORS.values())), legend=None),
            tooltip=[alt.Tooltip("PRIORITY:N", title="Priority"), alt.Tooltip("COUNT:Q", title=title, format=",")],
        )
    )
    labels = alt.Chart(data).mark_text(align="left", dx=4, color=INK, fontSize=11).encode(x="COUNT:Q", y=y, text="_label:N")
    return _base(bars + labels)
