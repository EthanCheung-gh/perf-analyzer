from __future__ import annotations

import re

import plotly.graph_objects as go

from .constants import PLOTLY_AXIS_STYLE, PLOTLY_COLORWAY


def is_auto_plotly_color(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    color = value.strip().lower()
    if not color:
        return True
    return bool(re.fullmatch(r"#00000[1-9a-f]", color))


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    color = hex_color.lstrip("#")
    if len(color) != 6:
        return f"rgba(37, 99, 235, {alpha})"
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def apply_chart_export_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        colorway=PLOTLY_COLORWAY,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#111827"},
        legend={
            "bgcolor": "rgba(255,255,255,0.82)",
            "bordercolor": "#e5e7eb",
            "borderwidth": 1,
        },
    )
    fig.update_xaxes(**PLOTLY_AXIS_STYLE)
    fig.update_yaxes(**PLOTLY_AXIS_STYLE)
    fig.update_polars(
        bgcolor="#ffffff",
        angularaxis={"gridcolor": "#e5e7eb", "linecolor": "#d1d5db"},
        radialaxis={"gridcolor": "#e5e7eb", "linecolor": "#d1d5db"},
    )

    for index, trace in enumerate(fig.data):
        color = PLOTLY_COLORWAY[index % len(PLOTLY_COLORWAY)]
        trace_type = getattr(trace, "type", "")
        if trace_type in {"scatter", "scattergl", "scatterpolar"}:
            line = getattr(trace, "line", None)
            marker = getattr(trace, "marker", None)
            if line is not None and is_auto_plotly_color(getattr(line, "color", None)):
                line.color = color
            if marker is not None and is_auto_plotly_color(getattr(marker, "color", None)):
                marker.color = color
            if getattr(trace, "fill", None) and is_auto_plotly_color(getattr(trace, "fillcolor", None)):
                trace.fillcolor = hex_to_rgba(color, 0.16)
        elif trace_type in {"bar", "box", "violin"}:
            marker = getattr(trace, "marker", None)
            if marker is not None and is_auto_plotly_color(getattr(marker, "color", None)):
                marker.color = color
    return fig


def figure_to_html_bytes(fig: go.Figure, include_plotlyjs: bool | str = True) -> bytes:
    apply_chart_export_theme(fig)
    html = fig.to_html(
        full_html=True,
        include_plotlyjs=include_plotlyjs,
        config={"responsive": True, "displaylogo": False},
    )
    return html.encode("utf-8-sig")
