from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from datetime import datetime
from io import BytesIO

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from .alerts import alert_segments
from .analysis import summarize
from .charts import figure_to_html_bytes
from .constants import GENERIC_MODE
from .models import Metric
from .utils import safe_filename


def dataframe_to_csv_bytes(data: pd.DataFrame) -> bytes:
    return data.to_csv(index=False).encode("utf-8-sig")


def with_display_label(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    if result["source"].nunique() > 1:
        result["display_scene"] = result["source"].astype(str) + " / " + result["scene"].astype(str)
    else:
        result["display_scene"] = result["scene"].astype(str)
    return result


def build_batch_export_zip(
    data: pd.DataFrame,
    selected_scenes: list[str],
    selected_metrics: list[str],
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]],
    metrics: list[Metric],
    analysis_mode: str,
    group_label: str,
    *,
    build_alerts_table: Callable[[pd.DataFrame, list[Metric], dict[str, float], dict[str, tuple[float | None, float | None]]], pd.DataFrame],
    build_sampling_interval_tables: Callable[[pd.DataFrame], tuple[pd.DataFrame, pd.DataFrame]],
    build_trend_figure: Callable[[pd.DataFrame, Metric, dict[str, float], dict[str, tuple[float | None, float | None]], str, bool, str, int, float], go.Figure],
    build_distribution_figure: Callable[[pd.DataFrame, Metric], go.Figure],
    build_alert_timeline_figure: Callable[[pd.DataFrame], go.Figure],
    build_sampling_interval_box: Callable[[pd.DataFrame], go.Figure],
    build_sampling_interval_line: Callable[[pd.DataFrame, str], go.Figure],
    export_mode: str = "轻量模式",
    export_options: dict[str, object] | None = None,
    trend_band_mode: str = "自动P5-P95",
    trend_show_rolling: bool = False,
    trend_rolling_mode: str = "按采样点数",
    trend_rolling_window: int = 5,
    trend_rolling_time_seconds: float = 300.0,
) -> bytes:
    filtered = with_display_label(data[data["scene"].isin(selected_scenes)].copy())
    use_shared_plotly = export_mode.startswith("轻量")
    chart_include_plotlyjs: bool | str = "../assets/plotly.min.js" if use_shared_plotly else True
    export_options = export_options or {}
    include_trend = bool(export_options.get("trend", True))
    include_distribution = bool(export_options.get("distribution", True))
    include_alert_timeline = bool(export_options.get("alert_timeline", True))
    include_sampling_interval = bool(export_options.get("sampling_interval", True))
    max_distribution_metrics = max(1, int(export_options.get("max_distribution_metrics", 5)))
    metric_lookup = {metric.key: metric for metric in metrics}
    alerts = build_alerts_table(filtered, metrics, thresholds, threshold_bounds)
    segments = alert_segments(filtered, thresholds, metrics, threshold_bounds)
    interval_data, interval_summary = build_sampling_interval_tables(filtered)
    summary = summarize(filtered, thresholds, metrics, threshold_bounds)

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "analysis_mode": "generic_timeseries" if analysis_mode == GENERIC_MODE else "performance",
        "group_label": group_label,
        "sources": list(filtered["source"].dropna().astype(str).unique()),
        "groups": list(filtered["scene"].dropna().astype(str).unique()),
        "metrics": [metric.key for metric in metrics],
        "selected_trend_metrics": selected_metrics,
        "export_mode": "shared_plotly_asset" if use_shared_plotly else "standalone_html",
        "export_options": {
            "trend": include_trend,
            "distribution": include_distribution,
            "alert_timeline": include_alert_timeline,
            "sampling_interval": include_sampling_interval,
            "max_distribution_metrics": max_distribution_metrics,
        },
        "assets": ["assets/plotly.min.js"] if use_shared_plotly else [],
        "charts": [],
        "tables": [],
    }

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if use_shared_plotly:
            archive.writestr("assets/plotly.min.js", get_plotlyjs().encode("utf-8"))

        tables = {
            "tables/summary.csv": summary,
            "tables/alerts.csv": alerts,
            "tables/alert_segments.csv": segments,
            "tables/sampling_interval_summary.csv": interval_summary,
            "tables/sampling_interval_points.csv": interval_data,
        }
        for path, table in tables.items():
            if not table.empty:
                archive.writestr(path, dataframe_to_csv_bytes(table))
                manifest["tables"].append(path)

        chart_count = 0
        if include_trend:
            for metric_key in selected_metrics:
                metric = metric_lookup.get(metric_key)
                if metric is None or metric.key not in filtered or filtered[metric.key].dropna().empty:
                    continue
                fig = build_trend_figure(
                    filtered,
                    metric,
                    thresholds,
                    threshold_bounds,
                    band_mode=trend_band_mode,
                    show_rolling=trend_show_rolling,
                    rolling_mode=trend_rolling_mode,
                    rolling_window=trend_rolling_window,
                    rolling_time_seconds=trend_rolling_time_seconds,
                )
                path = f"charts/{safe_filename('趋势_' + metric.label)}.html"
                archive.writestr(path, figure_to_html_bytes(fig, include_plotlyjs=chart_include_plotlyjs))
                manifest["charts"].append(path)
                chart_count += 1

        if include_distribution:
            distribution_count = 0
            for metric in metrics:
                if distribution_count >= max_distribution_metrics:
                    break
                if metric.key not in filtered or filtered[metric.key].dropna().empty:
                    continue
                fig = build_distribution_figure(filtered, metric)
                path = f"charts/{safe_filename('分布_' + metric.label)}.html"
                archive.writestr(path, figure_to_html_bytes(fig, include_plotlyjs=chart_include_plotlyjs))
                manifest["charts"].append(path)
                chart_count += 1
                distribution_count += 1

        if include_alert_timeline and not alerts.empty:
            path = "charts/异常时间轴.html"
            archive.writestr(path, figure_to_html_bytes(build_alert_timeline_figure(alerts), include_plotlyjs=chart_include_plotlyjs))
            manifest["charts"].append(path)
            chart_count += 1

        if include_sampling_interval and not interval_data.empty:
            path = "charts/采样间隔分布.html"
            archive.writestr(path, figure_to_html_bytes(build_sampling_interval_box(interval_data), include_plotlyjs=chart_include_plotlyjs))
            manifest["charts"].append(path)
            chart_count += 1
            line_scene = str(interval_data["display_scene"].dropna().iloc[0])
            line_path = f"charts/{safe_filename('采样间隔时间线_' + line_scene)}.html"
            archive.writestr(line_path, figure_to_html_bytes(build_sampling_interval_line(interval_data, line_scene), include_plotlyjs=chart_include_plotlyjs))
            manifest["charts"].append(line_path)
            chart_count += 1

        manifest["chart_count"] = chart_count
        manifest["table_count"] = len(manifest["tables"])
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8-sig"))

    return buffer.getvalue()
