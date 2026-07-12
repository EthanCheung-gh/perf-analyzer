# 分析灵活度增强 — 设计规格

> 第一批：高级筛选面板 + 报告章节可选

## Goal

增强 `perf-analyzer` 的分析灵活度，让用户在现有分析流水线中能自定义筛选条件（时间范围、指标条件、分类列过滤、采样降频）和报告内容（按需选择章节）。为后续第二批的衍生指标表达式引擎奠定交互基础。

## Non-Goals

- 不引入表达式引擎或自定义衍生指标（第二批）
- 不修改 Excel 数据读取逻辑
- 不增加新的分析 tab 或页面
- 不改变现有的核心算法（summarize、alert_segments、scene_decision_analysis 等）

## Context

当前筛选只支持按数据源和分组筛选，报告章节固定不可选。用户无法排除特定时间窗口的数据、无法按指标条件过滤采样行、无法选择报告内容。设计需兼容两种分析模式（应用性能 / 通用时序）。

## Proposed Architecture

### 数据流变更

```
当前:
  raw_data → apply_stable_window() → data → source+scene 筛选 → filtered_data → 各视图

新:
  raw_data → apply_stable_window() → data → source+scene 筛选 → filtered_data
  → apply_advanced_filters() [时间/指标条件/分类/降频] → final_data → 各视图
```

### 模块职责

| 模块 | 新增/修改 | 职责 |
|---|---|---|
| `analysis.py` | 新增 `apply_advanced_filters()` | 按时间范围、指标条件、分类列、降频参数过滤 DataFrame |
| `app.py` | 修改 `main()` | 侧边栏增加高级筛选控件，调用 `apply_advanced_filters()`，传递报告章节选择 |
| `views_report.py` | 修改 | 报告页新增章节选择 checkbox，透传至 `report.py` |
| `report.py` | 修改 `build_report_markdown()` 等 | 所有构建函数接受 `sections` 参数，按需输出 |
| `ui_state.py` | 修改 `build_ui_settings()` | 加入筛选条件和报告章节的状态快照 |
| `config.py` | 修改 | 加入筛选配置/报告章节的导出/导入 |
| `constants.py` | 修改 | 定义 `REPORT_SECTIONS`、`REPORT_SECTIONS_GENERIC` 等常量 |

### 高级筛选实现

**函数签名：**
```python
def apply_advanced_filters(
    data: pd.DataFrame,
    time_range: tuple[pd.Timestamp, pd.Timestamp] | None,
    metric_conditions: list[tuple[str, str, float]],  # [(key, op, value), ...]
    metric_condition_logic: str,  # "AND" | "OR"
    categorical_filters: dict[str, list[str]],  # {column: [allowed_values]}
    downsample_every_n: int | None,
    downsample_mode: str,  # "每N个点" | "每N秒"
    downsample_n: int,
) -> pd.DataFrame
```

**时间范围：** 先取数据的最小/最大时间戳展示给用户，用户通过 `st.slider` 选择起止范围。

**指标条件：** 提供 3 个预设条件行，每行 `[指标selectbox] [运算符selectbox] [值number_input]`，AND/OR 通过 radio 切换。指标列表来自当前的 `metric_by_key`。

**分类列筛选：** 自动检测 data 中不在 `META_COLUMNS` 且非数值型的列（`pd.api.types.is_object_dtype`），每列用一个 `st.multiselect` 展示其唯一值。

**采样降频：** 两种模式：
- "每N个点"：`group.iloc[::n]` 每隔 N 行取一行
- "每N秒"：以 `n` 秒为窗口做 `groupby(source, scene) + resample`，取每个窗口第一个值

### 报告章节实现

**常量定义：**
```python
REPORT_SECTIONS = {
    "conclusions": "测试结论",
    "decision": "决策分析",
    "release_gate": "发布门禁",
    "stability": "稳定性评分",
    "bottleneck": "瓶颈提示",
    "summary": "汇总数据",
    "alert_continuity": "告警持续性摘要",
    "segments": "异常段",
    "leak": "内存趋势检测",
    "trend_slope": "全指标趋势斜率",
    "efficiency": "资源效率",
    "config_recommendation": "配置建议",
    # "methodology" 始终包含
}
```

`build_report_markdown()` 等函数接受 `enabled_sections: set[str]` 参数，只渲染 `enabled_sections` 中的章节。`methodology` 和 `conclusions` 始终为 True。

## Files To Change

| 文件 | 改动 |
|---|---|
| `perf_analyzer/constants.py` | 新增 `REPORT_SECTIONS`、`REPORT_SECTIONS_GENERIC` 字典 |
| `perf_analyzer/analysis.py` | 新增 `apply_advanced_filters()` 函数 |
| `perf_analyzer/report.py` | `build_report_markdown()`、`build_generic_report_markdown()`、`build_report_pdf_summary_markdown()`、`build_generic_report_pdf_summary_markdown()`、`build_report_detail_tables()`、`build_generic_report_detail_tables()` 增加 `enabled_sections` 参数 |
| `perf_analyzer/ui_state.py` | `build_ui_settings()` 加入筛选条件和报告章节选择状态 |
| `perf_analyzer/config.py` | 配置导出/导入加入筛选和报告章节字段 |
| `perf_analyzer/views_report.py` | 报告页增加章节选择 checkbox 和高级筛选的侧边栏控件引入 |
| `app.py` | 侧边栏增加高级筛选 expander 及控件；报告页传入 `enabled_sections` |

## Testing Strategy

- 手动验证：
  1. 时间范围筛选后各 tab 数据正确减少
  2. 指标条件 AND/OR 逻辑正确（用已知数据用例验证）
  3. 分类列筛选只显示勾选的值
  4. 降采样后点数减少且趋势形状保持
  5. 报告仅包含勾选的章节
  6. 配置导出/导入后筛选和章节状态恢复

## Risks And Mitigations

| 风险 | 缓解 |
|---|---|
| 高级筛选和现有 source+scene 筛选重复/冲突 | 高级筛选在 source+scene 筛选之后执行，互不覆盖 |
| Streamlit 对动态表单（动态条件行数）支持较弱 | 固定 3 行预设条件行，空行自动跳过 |
| 降采样后统计值与原始数据不一致 | 降采样仅影响趋势图和原始数据显示，统计值仍基于全量 `final_data`；降采样默认为 1（不降） |
| 报告章节参数扩散到多个生成函数 | 统一用 `set[str]` 传递，所有函数在 `report.py` 内部共享 |

## Decision Summary

- 高级筛选在侧边栏新增 expander，在 source+scene 筛选之后执行
- 指标条件固定 3 行预设行，AND/OR 组合
- 分类列由数据自动发现
- 降采样支持按点数和按秒两种模式
- 报告章节全量勾选checkbox，结论和分析口径始终包含
- 配置 JSON 导出/导入覆盖筛选条件和报告章节选择
