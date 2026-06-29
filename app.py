from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from perf_analyzer.analysis import apply_stable_window, configuration_recommendation
from perf_analyzer.alerts import (
    format_duration,
    format_peak_offset,
    max_continuous_alert_minutes,
)
from perf_analyzer.config import (
    build_config_template,
    build_settings_config,
    config_analysis_mode,
    config_analysis_text,
    config_analysis_value,
    config_field_aliases,
    config_to_json_bytes,
    config_ui_list,
    configured_metric_from_import,
    metric_config_entry,
    metric_bounds_from_import,
    threshold_from_import,
)
from perf_analyzer.constants import (
    ANALYSIS_MODES,
    GENERIC_MODE,
    GENERIC_SAMPLE_FILE,
    PERFORMANCE_MODE,
    SAMPLE_FILE,
)
from perf_analyzer.export_adapter import build_batch_export_zip
from perf_analyzer.io import non_numeric_column_summary, read_single_workbook, timestamp_diagnostics
from perf_analyzer.metrics import discover_metrics, metric_by_key
from perf_analyzer.models import Metric
from perf_analyzer.ui_helpers import (
    render_system_info,
    sanitize_multiselect_state,
    sync_filter_context,
)
from perf_analyzer.ui_state import build_ui_settings
from perf_analyzer.utils import (
    parse_aliases,
)
from perf_analyzer.views_alerts import render_alerts
from perf_analyzer.views_baseline import render_baseline_growth, render_leak_detection, render_version_compare
from perf_analyzer.views_decision import render_decision, render_efficiency
from perf_analyzer.views_distribution import render_comparison, render_distribution
from perf_analyzer.views_overview import render_overview
from perf_analyzer.views_quality import render_config_validation, render_data_quality, render_timestamp_diagnostics
from perf_analyzer.views_report import render_configuration_recommendation, render_generic_report, render_report
from perf_analyzer.views_sampling import (
    render_sampling_interval,
)
from perf_analyzer.views_trend import render_trend


@st.cache_data(show_spinner=False)
def load_single_workbook(
    source_name: str,
    uploaded_file: bytes | None,
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return read_single_workbook(source_name, uploaded_file, field_alias_items, analysis_mode, sample_file)


def load_workbooks(
    files: tuple[tuple[str, bytes | None], ...],
    field_aliases: dict[str, tuple[str, ...]],
    analysis_mode: str = PERFORMANCE_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # 多文件上传时，每个 Excel 文件名作为 source，后续可用于版本/批次对比。
    systems = []
    frames = []
    field_alias_items = tuple(sorted(field_aliases.items()))
    for source_name, payload in files:
        system_info, data = load_single_workbook(source_name, payload, field_alias_items, analysis_mode)
        if not system_info.empty:
            systems.append(system_info)
        if not data.empty:
            frames.append(data)
    system = pd.concat(systems, ignore_index=True) if systems else pd.DataFrame()
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return system, data


@st.cache_data(show_spinner=False)
def load_timestamp_diagnostics(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str = PERFORMANCE_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return timestamp_diagnostics(files, field_alias_items, sample_file)


@st.cache_data(show_spinner=False)
def load_non_numeric_column_summary(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str = PERFORMANCE_MODE,
) -> pd.DataFrame:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return non_numeric_column_summary(files, field_alias_items, sample_file)


def parse_json_config(uploaded_file: object | None) -> dict:
    if uploaded_file is None:
        return {}
    try:
        payload = uploaded_file.getvalue()
        return json.loads(payload.decode("utf-8-sig"))
    except Exception as exc:
        st.sidebar.warning(f"配置文件读取失败：{exc}")
        return {}


def ensure_sample_file(path: Path) -> None:
    if not path.exists():
        st.error(f"未找到示例数据：{path}")
        st.stop()


def main() -> None:
    st.set_page_config(page_title="时序指标分析", page_icon="📈", layout="wide")

    with st.sidebar:
        st.header("数据源")
        uploaded_files = st.file_uploader(
            "上传 Excel 文件",
            type=["xlsx", "xls"],
            accept_multiple_files=True,
            help="可以一次上传多个 Excel。文件名会作为数据源名称，用于版本对比和多批次对比。",
        )
        settings_file = st.file_uploader(
            "导入分析配置",
            type=["json"],
            help="可选。导入字段别名、阈值、告警方向、泄漏阈值和稳定区间。配置只覆盖能匹配上的指标，其他指标继续使用自动默认值。",
        )
        imported_config = parse_json_config(settings_file)
        st.session_state["imported_config"] = imported_config
        if imported_config:
            st.caption("已加载分析配置；未匹配的指标会自动忽略。")
        default_mode = config_analysis_mode(imported_config)
        analysis_mode = st.selectbox(
            "分析模式",
            ANALYSIS_MODES,
            index=ANALYSIS_MODES.index(default_mode),
            help="应用性能模式会识别 CPU、内存、QPS 等性能语义；通用时序模式只识别时间戳和数值指标，适合温度、压力、质量测量等通用采样记录。",
        )
        group_label = st.text_input(
            "分组名称",
            value=config_analysis_text(imported_config, "group_label", "分组" if analysis_mode == GENERIC_MODE else "场景"),
            help="用于描述 Excel 中每个数据 sheet 的含义，例如场景、设备、工况、批次或实验组。",
        )

    page_title = "通用时序分析" if analysis_mode == GENERIC_MODE else "应用资源消耗分析"
    st.title(page_title)
    if analysis_mode == GENERIC_MODE:
        st.caption(f"当前模式：通用时序；每个数据 sheet 作为一个{group_label}分组。")
    use_sample = not uploaded_files
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    if use_sample:
        ensure_sample_file(sample_file)
        st.caption(f"当前使用示例数据：{sample_file}")
    else:
        st.caption(f"已上传 {len(uploaded_files)} 个 Excel 文件。")
    st.caption(f"读取规则：第一个 sheet 为元信息，其余 sheet 名作为{group_label}名。")

    with st.expander("自定义字段映射"):
        st.caption("多个别名用英文逗号分隔。系统会先匹配这里配置的字段名，再使用内置规则自动识别。")
        field_aliases = {
            field: parse_aliases(
                st.text_input(
                    label,
                    value=",".join(config_field_aliases(imported_config, field)),
                    placeholder="例如：字段A,字段B",
                    help=f"如果采集工具导出的 {label} 表头无法被自动识别，可以在这里填写额外别名，多个别名用英文逗号分隔。",
                )
            )
            for field, (label, _) in MAPPING_FIELDS.items()
        }

    slope_threshold = st.number_input(
        "内存疑似泄漏斜率阈值(MB/分钟)",
        min_value=0.0,
        value=config_analysis_value(imported_config, "memory_leak_slope_threshold", 2.0),
        step=0.5,
        help="性能模式用于内存泄漏检测；通用时序模式仅保存在导出配置中，不参与通用报告判断。",
    )

    st.header("稳定区间")
    warmup_minutes = st.number_input(
        "排除每个分组前 N 分钟",
        min_value=0.0,
        value=config_analysis_value(imported_config, "warmup_minutes", 0.0),
        step=0.5,
        help="用于排除启动预热、采集准备等早期尖峰。裁剪会按数据源 + 分组分别计算，不修改原始 Excel。",
    )

    if use_sample:
        files = (("示例数据", None),)
    else:
        files = tuple((file.name, file.getvalue()) for file in uploaded_files)

    # 加载 Excel 后先得到完整原始采样数据，再按稳定区间做分析视图。
    system_info, raw_data = load_workbooks(files, field_aliases, analysis_mode)
    timestamp_summary, timestamp_failures = load_timestamp_diagnostics(files, tuple(sorted(field_aliases.items())), analysis_mode)
    non_numeric_columns = load_non_numeric_column_summary(files, tuple(sorted(field_aliases.items())), analysis_mode)
    data = apply_stable_window(raw_data, warmup_minutes)
    render_timestamp_diagnostics(timestamp_summary, timestamp_failures, raw_data)
    if data.empty:
        st.warning("未读取到场景数据。请确认第一个 sheet 为系统信息，其余 sheet 分别为轻载、重载等场景采样数据。")
        render_system_info(system_info)
        return

    sources = list(data["source"].dropna().unique())
    scenes = list(data["scene"].dropna().unique())
    # 指标发现发生在数据加载之后：性能模式核心指标优先；通用模式中所有数值列都是动态指标。
    metrics = discover_metrics(data)
    render_config_validation(imported_config, metrics)
    with st.sidebar:
        st.header("阈值")
        st.caption("核心指标使用内置默认阈值；动态扩展指标默认使用当前数据 P95。可导入 JSON 配置覆盖阈值和方向。")
        thresholds = {}
        threshold_bounds = {}
        configured_metrics = []
        metric_config_count = sum(1 for metric in metrics if metric_config_entry(imported_config, metric))
        with st.expander("阈值配置", expanded=not imported_config):
            threshold_display = st.radio(
                "显示方式",
                ["配置命中指标", "全部指标"],
                index=0 if imported_config and metric_config_count else 1,
                horizontal=True,
                help="导入配置后可以只显示配置文件命中的指标；未显示的指标仍会使用导入值或自动默认值参与分析。",
            )
            if imported_config:
                st.caption(f"当前数据识别到 {len(metrics)} 个指标，配置命中 {metric_config_count} 个。")
            for metric in metrics:
                configured_metric = configured_metric_from_import(imported_config, metric)
                threshold_value = threshold_from_import(imported_config, metric)
                lower_bound, upper_bound = metric_bounds_from_import(imported_config, metric)
                show_metric_controls = threshold_display == "全部指标" or bool(metric_config_entry(imported_config, metric))
                if show_metric_controls:
                    direction = st.selectbox(
                        f"{metric.label} 告警方向",
                        ["越高越差", "越低越差"],
                        index=0 if configured_metric.higher_is_worse else 1,
                        key=f"direction_{metric.key}",
                        help="例如 CPU、内存、响应时间通常越高越差；FPS、成功率、QPS 在某些场景下可能越低越差。",
                    )
                    configured_metric = replace(configured_metric, higher_is_worse=direction == "越高越差")
                    threshold_value = st.number_input(
                        configured_metric.threshold_label,
                        min_value=0.0,
                        value=float(threshold_value),
                        step=1.0,
                        key=f"threshold_{metric.key}",
                        help="用于异常点、超阈次数、超阈占比、最大连续超阈和趋势图阈值线。不会修改原始数据。",
                    )
                configured_metrics.append(configured_metric)
                thresholds[metric.key] = threshold_value
                threshold_bounds[metric.key] = (lower_bound, upper_bound)
        metrics = configured_metrics

        st.header("筛选")
        default_sources = [source for source in config_ui_list(imported_config, "filters", "selected_sources", sources) if source in sources] or sources
        default_scenes = [scene for scene in config_ui_list(imported_config, "filters", "selected_groups", scenes) if scene in scenes] or scenes
        available_metrics = [metric for metric in metrics if metric.key in data and not data[metric.key].dropna().empty]
        available_metric_keys = [metric.key for metric in available_metrics]
        default_trend_metrics = [
            metric for metric in config_ui_list(imported_config, "filters", "selected_trend_metrics", available_metric_keys[:3]) if metric in available_metric_keys
        ] or available_metric_keys[:3]
        sync_filter_context(analysis_mode, sources, scenes, available_metric_keys)
        sanitize_multiselect_state("selected_sources", sources, default_sources)
        selected_sources_kwargs = {"default": default_sources} if "selected_sources" not in st.session_state else {}
        selected_sources = st.multiselect(
            "数据源",
            sources,
            key="selected_sources",
            help="选择要参与分析的数据源。多文件上传时，每个文件名就是一个数据源。",
            **selected_sources_kwargs,
        )
        sanitize_multiselect_state("selected_scenes", scenes, default_scenes)
        selected_scenes_kwargs = {"default": default_scenes} if "selected_scenes" not in st.session_state else {}
        selected_scenes = st.multiselect(
            group_label,
            scenes,
            key="selected_scenes",
            help=f"选择要参与分析的{group_label}。名称来自 Excel 的 sheet 名。",
            **selected_scenes_kwargs,
        )
        sanitize_multiselect_state("selected_trend_metrics", available_metric_keys, default_trend_metrics)
        selected_metrics_kwargs = {"default": default_trend_metrics} if "selected_trend_metrics" not in st.session_state else {}
        selected_metrics = st.multiselect(
            "趋势指标",
            available_metric_keys,
            key="selected_trend_metrics",
            format_func=lambda key: metric_by_key(metrics, key).label,
            help="选择趋势页要绘制的指标。这里不影响概览、报告和其他统计表。",
            **selected_metrics_kwargs,
        )

        current_config = build_settings_config(
            field_aliases,
            float(slope_threshold),
            float(warmup_minutes),
            metrics,
            thresholds,
            threshold_bounds,
            analysis_mode,
            group_label,
            build_ui_settings(),
        )
        st.download_button(
            "导出当前分析配置",
            config_to_json_bytes(current_config),
            file_name="perf_analyzer_config.json",
            mime="application/json",
            help="导出当前字段别名、分析参数、阈值、告警方向、筛选条件和图表/决策配置。下次可直接导入复用。",
        )
        template_config = build_config_template(
            field_aliases,
            float(slope_threshold),
            float(warmup_minutes),
            metrics,
            thresholds,
            threshold_bounds,
            analysis_mode,
            group_label,
            build_ui_settings(),
        )
        st.download_button(
            "下载配置模板 JSON",
            config_to_json_bytes(template_config),
            file_name="perf_analyzer_config_template.json",
            mime="application/json",
            help="生成一份带说明的可编辑模板，适合保存后手工调整字段、阈值、单位和图表默认项。",
        )

    filtered_data = data[data["source"].isin(selected_sources) & data["scene"].isin(selected_scenes)].copy()
    if filtered_data.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    with st.sidebar:
        st.header("批量导出")
        batch_export_mode = st.radio(
            "图表 HTML 模式",
            ["轻量模式（共享Plotly）", "完整离线模式"],
            horizontal=False,
            help="轻量模式在 ZIP 中只放一份 Plotly JS，体积更小；完整离线模式每个 HTML 都可单独拎出来打开，但 ZIP 更大。",
        )
        with st.expander("导出范围", expanded=False):
            export_trend = st.checkbox("趋势图", value=True, key="batch_export_trend")
            export_distribution = st.checkbox("分布图", value=True, key="batch_export_distribution")
            export_alert_timeline = st.checkbox("异常时间轴", value=True, key="batch_export_alert_timeline")
            export_sampling_interval = st.checkbox("采样间隔图", value=True, key="batch_export_sampling_interval")
            max_distribution_metrics = st.number_input(
                "分布图最多指标数",
                min_value=1,
                max_value=50,
                value=5,
                step=1,
                key="batch_export_max_distribution_metrics",
                disabled=not export_distribution,
                help="分布图按当前指标顺序导出前 N 个有效指标，避免 ZIP 过大。",
            )
        st.download_button(
            "下载图表与表格 ZIP",
            build_batch_export_zip(
                filtered_data,
                selected_scenes,
                selected_metrics,
                thresholds,
                threshold_bounds,
                metrics,
                analysis_mode,
                group_label,
                batch_export_mode,
                {
                    "trend": export_trend,
                    "distribution": export_distribution,
                    "alert_timeline": export_alert_timeline,
                    "sampling_interval": export_sampling_interval,
                    "max_distribution_metrics": int(max_distribution_metrics),
                },
            ),
            file_name=f"perf_analyzer_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mime="application/zip",
            help="导出当前筛选条件下的核心图表 HTML、摘要表、异常表、异常段和采样间隔表。",
        )

    config_table = pd.DataFrame()
    config_notes: list[str] = []

    if analysis_mode == GENERIC_MODE:
        tabs = st.tabs(["概览", "趋势", "对比", "基准增长", "版本对比", "分布", "异常", "数据质量", "报告", "元信息", "原始数据"])
        with tabs[0]:
            render_overview(filtered_data, thresholds, metrics, threshold_bounds)
        with tabs[1]:
            render_trend(filtered_data, selected_scenes, selected_metrics, thresholds, threshold_bounds, metrics)
        with tabs[2]:
            render_comparison(filtered_data, selected_scenes, metrics)
        with tabs[3]:
            render_baseline_growth(filtered_data, selected_scenes, metrics)
        with tabs[4]:
            render_version_compare(filtered_data, selected_scenes, metrics)
        with tabs[5]:
            render_distribution(filtered_data, selected_scenes, metrics)
        with tabs[6]:
            render_alerts(filtered_data, selected_scenes, thresholds, metrics, threshold_bounds)
        with tabs[7]:
            render_data_quality(filtered_data, metrics, non_numeric_columns)
        with tabs[8]:
            render_generic_report(filtered_data, thresholds, metrics, group_label, threshold_bounds)
        with tabs[9]:
            selected_system = system_info[system_info["数据源"].isin(selected_sources)] if "数据源" in system_info else system_info
            render_system_info(selected_system)
        with tabs[10]:
            filtered = filtered_data.copy()
            render_sampling_interval(filtered, selected_scenes)
            st.dataframe(filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "下载当前筛选数据 CSV",
                filtered.to_csv(index=False).encode("utf-8-sig"),
                file_name="timeseries_filtered.csv",
                mime="text/csv",
            )
    else:
        tabs = st.tabs(["概览", "趋势", "对比", "配置建议", "基准增长", "泄漏检测", "版本对比", "效率", "决策", "分布", "异常", "数据质量", "报告", "系统信息", "原始数据"])
        with tabs[0]:
            render_overview(filtered_data, thresholds, metrics, threshold_bounds)
        with tabs[1]:
            render_trend(filtered_data, selected_scenes, selected_metrics, thresholds, threshold_bounds, metrics)
        with tabs[2]:
            render_comparison(filtered_data, selected_scenes, metrics)
        with tabs[3]:
            config_table, config_notes = render_configuration_recommendation(filtered_data, slope_threshold)
        with tabs[4]:
            render_baseline_growth(filtered_data, selected_scenes, metrics)
        with tabs[5]:
            render_leak_detection(filtered_data, selected_scenes, slope_threshold, metrics)
        with tabs[6]:
            render_version_compare(filtered_data, selected_scenes, metrics)
        with tabs[7]:
            render_efficiency(filtered_data, selected_scenes)
        with tabs[8]:
            render_decision(filtered_data, selected_scenes, thresholds, metrics, slope_threshold, threshold_bounds)
        with tabs[9]:
            render_distribution(filtered_data, selected_scenes, metrics)
        with tabs[10]:
            render_alerts(filtered_data, selected_scenes, thresholds, metrics, threshold_bounds)
        with tabs[11]:
            render_data_quality(filtered_data, metrics, non_numeric_columns)
        with tabs[12]:
            if config_table.empty:
                config_table, config_notes = configuration_recommendation(
                    filtered_data,
                    test_cpu_cores=8,
                    target_cpu_utilization=70.0,
                    minimum_cpu_cores=2,
                    system_reserved_memory_gb=2.0,
                    minimum_memory_gb=4,
                    minimum_free_disk_gb=10,
                    recommendation_factor=1.5,
                    slope_threshold=slope_threshold,
                )
            render_report(filtered_data, thresholds, slope_threshold, metrics, threshold_bounds, config_table, config_notes)
        with tabs[13]:
            selected_system = system_info[system_info["数据源"].isin(selected_sources)] if "数据源" in system_info else system_info
            render_system_info(selected_system)
        with tabs[14]:
            filtered = filtered_data.copy()
            render_sampling_interval(filtered, selected_scenes)
            st.dataframe(filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "下载当前筛选数据 CSV",
                filtered.to_csv(index=False).encode("utf-8-sig"),
                file_name="resource_metrics_filtered.csv",
                mime="text/csv",
            )


if __name__ == "__main__":
    main()
