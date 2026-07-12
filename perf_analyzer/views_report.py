from __future__ import annotations

import pandas as pd
import streamlit as st

from .analysis import configuration_recommendation
from .config import config_ui_float, config_ui_int
from .constants import REPORT_SECTIONS, REPORT_SECTIONS_ALWAYS, REPORT_SECTIONS_GENERIC
from .models import Metric
from .report import (
    build_conclusions,
    build_generic_conclusions,
    build_generic_report_detail_tables,
    build_generic_report_figure_images,
    build_generic_report_markdown,
    build_generic_report_pdf_summary_markdown,
    build_report_detail_tables,
    build_report_details_xlsx_bytes,
    build_report_docx_bytes,
    build_report_figure_images,
    build_report_html,
    build_report_markdown,
    build_report_pdf_bytes,
    build_report_pdf_summary_markdown,
    build_report_zip_bytes,
)


def render_configuration_recommendation(data: pd.DataFrame, slope_threshold: float) -> tuple[pd.DataFrame, list[str]]:
    st.subheader("最低运行配置建议")
    st.caption("该结论基于当前筛选数据推导，适合做初步配置建议；正式发布最低配置前，仍建议在目标低配机器上实测验证。")

    imported_config = st.session_state.get("imported_config", {})
    col1, col2, col3 = st.columns(3)
    test_cpu_cores = col1.number_input(
        "测试机CPU核数",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "test_cpu_cores", 8),
        step=1,
        key="config_test_cpu_cores",
        help="采集性能数据时测试机的逻辑 CPU 核数，用于把 CPU P95 换算成目标机器核心需求。",
    )
    target_cpu_utilization = col2.number_input(
        "目标CPU利用率上限(%)",
        min_value=30.0,
        max_value=95.0,
        value=config_ui_float(imported_config, "configuration_recommendation", "target_cpu_utilization", 70.0),
        step=5.0,
        key="config_target_cpu_utilization",
        help="希望目标机器长期运行时 CPU 不超过的利用率。通常 70% 是比较通用的保守值。",
    )
    minimum_cpu_cores = col3.number_input(
        "最低CPU核数下限",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "minimum_cpu_cores", 2),
        step=1,
        key="config_minimum_cpu_cores",
        help="无论公式估算结果多低，最低配置都不会低于这个核数。",
    )

    col4, col5, col6 = st.columns(3)
    system_reserved_memory_gb = col4.number_input(
        "系统和后台预留内存(GB)",
        min_value=0.0,
        value=config_ui_float(imported_config, "configuration_recommendation", "system_reserved_memory_gb", 2.0),
        step=0.5,
        key="config_reserved_memory_gb",
        help="为操作系统、后台服务、运行时和缓存预留的内存，会叠加到应用内存峰值上。",
    )
    minimum_memory_gb = col5.number_input(
        "最低内存下限(GB)",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "minimum_memory_gb", 4),
        step=1,
        key="config_minimum_memory_gb",
        help="无论公式估算结果多低，最低配置都不会低于这个内存容量。",
    )
    minimum_free_disk_gb = col6.number_input(
        "最低磁盘剩余空间(GB)",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "minimum_free_disk_gb", 10),
        step=1,
        key="config_minimum_free_disk_gb",
        help="给安装包、日志、缓存、临时文件和运行数据预留的最低剩余磁盘空间。",
    )

    recommendation_factor = st.slider(
        "推荐配置安全系数",
        min_value=1.0,
        max_value=2.5,
        value=config_ui_float(imported_config, "configuration_recommendation", "recommendation_factor", 1.5),
        step=0.1,
        key="config_recommendation_factor",
        help="推荐配置会在最低配置基础上乘以该系数。系数越高，余量越大。",
    )
    config_table, notes = configuration_recommendation(
        data,
        int(test_cpu_cores),
        float(target_cpu_utilization),
        int(minimum_cpu_cores),
        float(system_reserved_memory_gb),
        int(minimum_memory_gb),
        int(minimum_free_disk_gb),
        float(recommendation_factor),
        slope_threshold,
    )

    st.dataframe(config_table, use_container_width=True, hide_index=True)

    st.markdown("**推导说明**")
    for note in notes:
        st.write(f"- {note}")

    st.markdown("**是否需要更多数据指标**")
    st.write("- 如果要更准确估算 CPU 核数，最好补充每核 CPU 使用率、进程 CPU 时间、任务吞吐量、响应时间或队列长度。只有总 CPU% 时，只能按总体占用近似换算。")
    st.write("- 如果软件有并发、批处理或服务端请求，建议补充并发数、TPS/QPS、任务量、数据规模，才能把配置结论和业务容量绑定。")
    st.write("- 如果 IO 可能是瓶颈，建议补充磁盘读写吞吐、IOPS、IO 等待时间、网络吞吐和错误重试次数。")
    st.write("- 如果需要正式发布最低配置，建议在至少一台目标低配机器上跑关键场景和长稳场景验证。")
    return config_table, notes


def render_report(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    slope_threshold: float,
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
    config_table: pd.DataFrame | None = None,
    config_notes: list[str] | None = None,
) -> None:
    st.subheader("测试结论与报告导出")
    conclusions = build_conclusions(data, thresholds, slope_threshold, metrics, threshold_bounds)
    for item in conclusions:
        st.write(f"- {item}")

    st.subheader("报告章节配置")
    enabled_sections: set[str] = set()
    with st.form("report_sections_form"):
        for section_id, section_label in REPORT_SECTIONS.items():
            default_enabled = st.session_state.get(f"report_section_{section_id}", True)
            is_enabled = st.checkbox(
                section_label,
                value=default_enabled,
                key=f"report_section_{section_id}",
                disabled=section_id in REPORT_SECTIONS_ALWAYS,
            )
            if is_enabled or section_id in REPORT_SECTIONS_ALWAYS:
                enabled_sections.add(section_id)
        st.caption(f"已选择 {len(enabled_sections)}/{len(REPORT_SECTIONS)} 个章节（分析口径始终包含）")
        st.form_submit_button("应用并刷新报告", use_container_width=True)

    markdown_report = build_report_markdown(data, thresholds, slope_threshold, metrics, threshold_bounds, config_table, config_notes, enabled_sections=enabled_sections)
    html_report = build_report_html(markdown_report, "应用资源消耗分析报告")
    pdf_markdown_report = build_report_pdf_summary_markdown(data, thresholds, slope_threshold, metrics, threshold_bounds, config_table, config_notes, enabled_sections=enabled_sections)
    detail_tables = build_report_detail_tables(data, thresholds, slope_threshold, metrics, threshold_bounds, config_table)
    details_xlsx = build_report_details_xlsx_bytes(detail_tables)
    pdf_images, image_errors = build_report_figure_images(data, thresholds, slope_threshold, metrics, threshold_bounds)
    docx_report = None
    docx_error = ""
    try:
        docx_report = build_report_docx_bytes(markdown_report)
    except RuntimeError as exc:
        docx_error = str(exc)
    pdf_report = None
    pdf_error = ""
    try:
        pdf_report = build_report_pdf_bytes(pdf_markdown_report, "应用资源消耗分析报告", pdf_images)
    except RuntimeError as exc:
        pdf_error = str(exc)
    zip_report = build_report_zip_bytes(markdown_report, html_report, docx_report, pdf_report, details_xlsx, "resource_report")
    st.download_button(
        "下载 Markdown 报告",
        markdown_report.encode("utf-8-sig"),
        file_name="resource_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "下载 HTML 报告",
        html_report.encode("utf-8"),
        file_name="resource_report.html",
        mime="text/html",
    )
    if docx_report is not None:
        st.download_button(
            "下载 Word 报告",
            docx_report,
            file_name="resource_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    else:
        st.warning(docx_error)
    if pdf_report is not None:
        st.download_button(
            "下载 PDF 报告",
            pdf_report,
            file_name="resource_report.pdf",
            mime="application/pdf",
        )
    else:
        st.warning(pdf_error)
    for image_error in sorted(set(image_errors)):
        st.warning(image_error)
    st.download_button(
        "下载报告 ZIP",
        zip_report,
        file_name="resource_report.zip",
        mime="application/zip",
        help="打包完整 Markdown、HTML、PDF 摘要、明细 Excel 和可用时的 Word 报告。",
    )
    st.caption("PDF 为摘要报告，适合归档和发送；完整明细见 ZIP 内 HTML、Markdown 和 Excel。")


def render_generic_report(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    group_label: str,
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> None:
    st.subheader("分析报告导出")
    conclusions = build_generic_conclusions(data, thresholds, metrics, threshold_bounds)
    for item in conclusions:
        st.write(f"- {item}")

    st.subheader("报告章节配置")
    enabled_sections: set[str] = set()
    with st.form("report_sections_form_generic"):
        for section_id, section_label in REPORT_SECTIONS_GENERIC.items():
            default_enabled = st.session_state.get(f"report_section_{section_id}", True)
            is_enabled = st.checkbox(
                section_label,
                value=default_enabled,
                key=f"report_section_{section_id}",
                disabled=section_id in REPORT_SECTIONS_ALWAYS,
            )
            if is_enabled or section_id in REPORT_SECTIONS_ALWAYS:
                enabled_sections.add(section_id)
        st.caption(f"已选择 {len(enabled_sections)}/{len(REPORT_SECTIONS_GENERIC)} 个章节")
        st.form_submit_button("应用并刷新报告", use_container_width=True)

    markdown_report = build_generic_report_markdown(data, thresholds, metrics, group_label, threshold_bounds, enabled_sections=enabled_sections)
    html_report = build_report_html(markdown_report, "通用时序分析报告")
    pdf_markdown_report = build_generic_report_pdf_summary_markdown(data, thresholds, metrics, group_label, threshold_bounds, enabled_sections=enabled_sections)
    detail_tables = build_generic_report_detail_tables(data, thresholds, metrics, threshold_bounds)
    details_xlsx = build_report_details_xlsx_bytes(detail_tables)
    pdf_images, image_errors = build_generic_report_figure_images(data, thresholds, metrics, threshold_bounds)
    docx_report = None
    docx_error = ""
    try:
        docx_report = build_report_docx_bytes(markdown_report)
    except RuntimeError as exc:
        docx_error = str(exc)
    pdf_report = None
    pdf_error = ""
    try:
        pdf_report = build_report_pdf_bytes(pdf_markdown_report, "通用时序分析报告", pdf_images)
    except RuntimeError as exc:
        pdf_error = str(exc)
    zip_report = build_report_zip_bytes(markdown_report, html_report, docx_report, pdf_report, details_xlsx, "timeseries_report")
    st.download_button(
        "下载 Markdown 报告",
        markdown_report.encode("utf-8-sig"),
        file_name="timeseries_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "下载 HTML 报告",
        html_report.encode("utf-8"),
        file_name="timeseries_report.html",
        mime="text/html",
    )
    if docx_report is not None:
        st.download_button(
            "下载 Word 报告",
            docx_report,
            file_name="timeseries_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    else:
        st.warning(docx_error)
    if pdf_report is not None:
        st.download_button(
            "下载 PDF 报告",
            pdf_report,
            file_name="timeseries_report.pdf",
            mime="application/pdf",
        )
    else:
        st.warning(pdf_error)
    for image_error in sorted(set(image_errors)):
        st.warning(image_error)
    st.download_button(
        "下载报告 ZIP",
        zip_report,
        file_name="timeseries_report.zip",
        mime="application/zip",
        help="打包完整 Markdown、HTML、PDF 摘要、明细 Excel 和可用时的 Word 报告。",
    )
    st.caption("PDF 为摘要报告，适合归档和发送；完整明细见 ZIP 内 HTML、Markdown 和 Excel。")
