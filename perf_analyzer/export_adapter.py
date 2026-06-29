from __future__ import annotations

import pandas as pd

from .export import build_batch_export_zip as build_batch_export_zip_core
from .models import Metric
from .views_alerts import build_alert_timeline_figure, build_alerts_table
from .views_distribution import build_distribution_figure
from .views_sampling import build_sampling_interval_box, build_sampling_interval_line, build_sampling_interval_tables
from .views_trend import build_trend_figure


def build_batch_export_zip(
    data: pd.DataFrame,
    selected_scenes: list[str],
    selected_metrics: list[str],
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]],
    metrics: list[Metric],
    analysis_mode: str,
    group_label: str,
    export_mode: str = "轻量模式",
    export_options: dict[str, object] | None = None,
) -> bytes:
    return build_batch_export_zip_core(
        data,
        selected_scenes,
        selected_metrics,
        thresholds,
        threshold_bounds,
        metrics,
        analysis_mode,
        group_label,
        build_alerts_table=build_alerts_table,
        build_sampling_interval_tables=build_sampling_interval_tables,
        build_trend_figure=build_trend_figure,
        build_distribution_figure=build_distribution_figure,
        build_alert_timeline_figure=build_alert_timeline_figure,
        build_sampling_interval_box=build_sampling_interval_box,
        build_sampling_interval_line=build_sampling_interval_line,
        export_mode=export_mode,
        export_options=export_options,
    )
