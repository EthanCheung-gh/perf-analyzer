from __future__ import annotations

import streamlit as st

from .constants import REPORT_SECTIONS, REPORT_SECTIONS_GENERIC


def session_value(key: str, default: object) -> object:
    return st.session_state.get(key, default)


def build_ui_settings() -> dict:
    return {
        "trend": {
            "show_rolling": session_value("trend_show_rolling", True),
            "rolling_mode": session_value("trend_rolling_mode", "按采样点数"),
            "rolling_window": session_value("trend_rolling_window", 5),
            "rolling_time_seconds": session_value("trend_rolling_time_seconds", 300.0),
            "band_mode": session_value("trend_band_mode", "自动P5-P95"),
        },
        "alerts": {
            "before_minutes": session_value("alert_before_minutes", 5.0),
            "after_minutes": session_value("alert_after_minutes", 5.0),
            "normalize_linked": session_value("alert_normalize_linked", True),
            "linked_metrics": session_value("alert_linked_metrics", []),
        },
        "version_compare": {
            "stat": session_value("version_compare_stat", "p95"),
            "metric": session_value("version_compare_metric", ""),
            "baseline_source": session_value("version_compare_baseline_source", ""),
            "regression_threshold": session_value("version_regression_threshold", 15.0),
            "scenes": session_value("version_compare_scenes", []),
        },
        "baseline_growth": {
            "baseline": session_value("baseline_growth_baseline", ""),
            "stat": session_value("baseline_growth_stat", "p95"),
            "metric": session_value("baseline_growth_metric", ""),
        },
        "distribution": {
            "metric": session_value("distribution_metric", ""),
            "control_metric": session_value("control_chart_metric", ""),
            "control_scene": session_value("control_chart_scene", ""),
        },
        "efficiency": {
            "metric": session_value("efficiency_metric", ""),
            "scatter_y": session_value("efficiency_scatter_y", ""),
        },
        "sampling_interval": {
            "scene": session_value("sampling_interval_scene", ""),
        },
        "decision": {
            "max_allowed_level": session_value("decision_max_allowed_level", "中风险"),
            "fail_on_leak": session_value("decision_fail_on_leak", True),
            "fail_on_any_alert": session_value("decision_fail_on_any_alert", False),
            "fail_on_errors": session_value("decision_fail_on_errors", False),
        },
        "capacity": {
            "test_cpu_cores": session_value("capacity_test_cpu_cores", 8),
            "target_cpu_utilization": session_value("capacity_target_cpu_utilization", 70.0),
            "reserved_memory_gb": session_value("capacity_reserved_memory_gb", 2.0),
            "throughput_targets": session_value("capacity_throughput_targets", "50,100,200"),
        },
        "configuration_recommendation": {
            "test_cpu_cores": session_value("config_test_cpu_cores", 8),
            "target_cpu_utilization": session_value("config_target_cpu_utilization", 70.0),
            "minimum_cpu_cores": session_value("config_minimum_cpu_cores", 2),
            "system_reserved_memory_gb": session_value("config_reserved_memory_gb", 2.0),
            "minimum_memory_gb": session_value("config_minimum_memory_gb", 4),
            "minimum_free_disk_gb": session_value("config_minimum_free_disk_gb", 10),
            "recommendation_factor": session_value("config_recommendation_factor", 1.5),
        },
        "filters": {
            "selected_sources": session_value("selected_sources", []),
            "selected_groups": session_value("selected_scenes", []),
            "selected_trend_metrics": session_value("selected_trend_metrics", []),
            "time_start": str(session_value("filter_time_start", "")),
            "time_end": str(session_value("filter_time_end", "")),
            "metric_condition_logic": session_value("filter_metric_logic", "AND"),
            "downsample_enabled": session_value("filter_downsample_enabled", False),
            "downsample_n": session_value("filter_downsample_n", 5),
        },
        "report": {
            "sections": {
                section_id: session_value(f"report_section_{section_id}", True)
                for section_id in list(dict.fromkeys([*REPORT_SECTIONS, *REPORT_SECTIONS_GENERIC]))
            },
        },
    }
