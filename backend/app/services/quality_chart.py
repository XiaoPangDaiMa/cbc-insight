"""数据质量图（FR-13，P2）。

这张图的读者不是"看热闹的人"，而是"准备拿这份数据下结论的人"。它要回答三个问题：

1. 哪几列缺得厉害（完整率）——决定能不能对那一列下结论；
2. 六项数据质量指标各得多少分（DQ-01~06）——决定这份数据整体可信到什么程度；
3. 清洗到底删掉了什么（剔除原因）——决定"剩下的 N 行"里有没有系统性缺口。

三件事放同一张图里必然互相挤压，所以拆成三个独立 panel，前端纵向排列。

**颜色一律不在这里写**：option 里不出现任何色值，由前端的主题（`tokens.generated.css` →
ECharts 主题）注入，这样屏幕图与报告图不会各走一路（NFR-M-07 / RK-22）。
"""

from __future__ import annotations

from typing import Any

from app.pipeline.fielddict import FieldDictionary

#: DQ 六项的中文名（3.6 / FR-04）
DQ_TEXT = {
    "DQ-01": "关键字段完整率",
    "DQ-02": "记录唯一率",
    "DQ-03": "值域合规率",
    "DQ-04": "单位可判定率",
    "DQ-05": "逻辑一致率",
    "DQ-06": "判定可解释率",
}

#: 剔除原因的中文名（S4 的 removed_by_reason 键）
REMOVED_TEXT = {
    "duplicate": "完全重复行",
    "core_all_null": "核心字段全空",
    "out_of_domain": "值域外的脏值",
    "logic_violation": "逻辑矛盾",
}

#: 完整率低于这个值就在图注里点名（不是"报警"，是"告知"）
LOW_COMPLETENESS = 0.9


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _completeness_panel(completeness: dict[str, float], fields: FieldDictionary) -> dict[str, Any]:
    """各列完整率：横向条形，最差的排在最上面（人的视线从上面开始）。"""
    items = [(metric, float(ratio)) for metric, ratio in completeness.items()]
    items.sort(key=lambda pair: pair[1])
    labels = [fields.name_cn(metric) or metric for metric, _ in items]
    values = [round(ratio * 100, 2) for _, ratio in items]
    option = {
        "grid": {"left": 96, "right": 56, "top": 16, "bottom": 28},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "value", "min": 0, "max": 100, "name": "完整率(%)", "nameLocation": "middle", "nameGap": 24},
        "yAxis": {"type": "category", "data": labels, "axisTick": {"show": False}},
        "series": [
            {
                "type": "bar",
                "data": values,
                "barMaxWidth": 14,
                "label": {"show": True, "position": "right", "formatter": "{c}%"},
                "markLine": {
                    "symbol": "none",
                    "silent": True,
                    "label": {"formatter": f"{int(LOW_COMPLETENESS * 100)}%"},
                    "data": [{"xAxis": LOW_COMPLETENESS * 100}],
                },
            }
        ],
    }
    return {"id": "completeness", "title": "各字段完整率", "unit": "%", "echarts_option": option}


def _dq_panel(dq: dict[str, float | None]) -> dict[str, Any]:
    """六项质量指标：0–100 分，缺项（None）留空而不是画成 0。"""
    codes = [code for code in DQ_TEXT if code in dq]
    labels = [DQ_TEXT[code] for code in codes]
    # None → 让 ECharts 画成空档：0 会被读成"这项得了 0 分"，二者含义完全不同
    values = [None if dq[code] is None else round(float(dq[code]) * 100, 2) for code in codes]
    option = {
        "grid": {"left": 120, "right": 56, "top": 16, "bottom": 28},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "value", "min": 0, "max": 100, "name": "得分(%)", "nameLocation": "middle", "nameGap": 24},
        "yAxis": {"type": "category", "data": labels, "axisTick": {"show": False}},
        "series": [
            {
                "type": "bar",
                "data": values,
                "barMaxWidth": 14,
                "label": {
                    "show": True,
                    "position": "right",
                    "formatter": "{c}%",
                },
            }
        ],
    }
    return {"id": "dq", "title": "数据质量指标（DQ-01~06）", "unit": "%", "echarts_option": option}


def _removed_panel(removed: dict[str, int]) -> dict[str, Any] | None:
    """清洗剔除的原因分布。一条都没剔过就不出这张图——画一个空饼图毫无信息。"""
    items = [(key, int(count)) for key, count in removed.items() if count]
    if not items:
        return None
    items.sort(key=lambda pair: pair[1], reverse=True)
    data = [{"name": REMOVED_TEXT.get(key, key), "value": count} for key, count in items]
    option = {
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} 行 ({d}%)"},
        "legend": {"bottom": 0, "icon": "circle"},
        "series": [
            {
                "type": "pie",
                "radius": ["42%", "68%"],
                "center": ["50%", "46%"],
                "avoidLabelOverlap": True,
                "label": {"formatter": "{b} {c} 行"},
                "data": data,
            }
        ],
    }
    return {"id": "removed", "title": "清洗剔除原因", "unit": "行", "echarts_option": option}


def _caption(
    dataset_rows: int,
    columns: int,
    completeness: dict[str, float],
    fields: FieldDictionary,
    dq: dict[str, float | None],
    removed: dict[str, int],
) -> str:
    """一句话结论。措辞里不出现"显著/提示/可能"，只陈述可核对的事实。"""
    # 不能写"原始 N 行 × M 列"：M 是**识别出的字段数**，源文件列数可能更多（DS-02 是 20 列
    # 只识别出 15 个），写成"M 列"会让人以为源文件就这么宽。
    parts: list[str] = [f"原始 {dataset_rows} 行，识别出 {columns} 个字段"]

    if completeness:
        worst_metric, worst_ratio = min(completeness.items(), key=lambda pair: pair[1])
        if worst_ratio < LOW_COMPLETENESS:
            label = fields.name_cn(worst_metric) or worst_metric
            parts.append(f"完整率最低的是{label} {_pct(worst_ratio)}")
        else:
            parts.append(f"各字段完整率均不低于 {_pct(LOW_COMPLETENESS)}")

    scored = {code: value for code, value in dq.items() if value is not None}
    if scored:
        worst_code, worst_value = min(scored.items(), key=lambda pair: pair[1])
        parts.append(f"DQ 最低项 {worst_code}（{DQ_TEXT.get(worst_code, worst_code)}）{_pct(worst_value)}")
        missing = [code for code, value in dq.items() if value is None]
        if missing:
            parts.append(f"{'、'.join(missing)} 未计算")
    else:
        parts.append("DQ 指标未计算")

    total_removed = sum(int(count) for count in removed.values())
    if total_removed:
        top_key, top_count = max(removed.items(), key=lambda pair: pair[1])
        parts.append(
            f"清洗共剔除 {total_removed} 行，其中{REMOVED_TEXT.get(top_key, top_key)} {top_count} 行"
        )
    else:
        parts.append("清洗未剔除任何行")

    return "；".join(parts) + "。"


def quality_chart(dataset, fields: FieldDictionary, *, settings=None) -> dict[str, Any]:
    """生成质量图载荷。

    ``dataset`` 用 ``dataset.quality``（S3 的落库结果）与 ``dataset.clean_report``（S4 的
    落库结果）——**不重新读 parquet、不重算**：质量图讲的是"当时那次清洗做了什么"，
    重算出来的数字和报告里的数字对不上，比没有这张图更糟。
    """
    quality = dataset.quality or {}
    completeness = {str(k): float(v) for k, v in (quality.get("completeness") or {}).items()}
    dq = {str(k): (None if v is None else float(v)) for k, v in (quality.get("dq") or {}).items()}
    clean = dataset.clean_report or {}
    removed = {str(k): int(v) for k, v in (clean.get("removed_by_reason") or {}).items()}

    panels = [_completeness_panel(completeness, fields), _dq_panel(dq)]
    removed_panel = _removed_panel(removed)
    if removed_panel is not None:
        panels.append(removed_panel)

    rows = int((clean.get("before") or {}).get("rows") or quality.get("rows") or dataset.rows or 0)
    columns = int(quality.get("columns") or dataset.columns or 0)

    return {
        "kind": "quality",
        "title": "数据质量",
        "metric": None,
        "unit": "",
        # 质量图没有"点位"，返回空列表而不是省略字段：前端对 points 的处理保持唯一分支
        "points": [],
        "sampled": False,
        "caption": _caption(rows, columns, completeness, fields, dq, removed),
        "caption_branch": "quality",
        "supporting": {
            "rows": rows,
            "columns": columns,
            "completeness": {k: round(v, 4) for k, v in completeness.items()},
            "dq": {k: (None if v is None else round(v, 4)) for k, v in dq.items()},
            "removed_by_reason": removed,
            "low_completeness": LOW_COMPLETENESS,
        },
        "panels": panels,
    }
