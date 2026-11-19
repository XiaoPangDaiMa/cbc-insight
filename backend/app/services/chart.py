"""FR-09/10/11 图表配置生成（ECharts option + 点位载荷 + 一句话结论）。

三条约束决定了这里的写法：

1. **不返回颜色**。option 里只出现语义（"偏高/正常/偏低"），颜色由前端 ECharts 主题
   按 ``theme/tokens.json`` 注入（NFR-M-07）。后端返回十六进制色值的那一刻，
   屏幕图与报告图就开始各自漂移（RK-22）。
2. **不返回宽表**。点位载荷 ``points[]`` 只有 4 个标量，≤ 2000 点（NFR-P-09 / RK-21）。
3. **图、点位、文案由同一次计算产出**（8.1 关于图表接口的三样产出）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.core.config import Settings, get_settings
from app.pipeline.captions import (
    caption_box,
    caption_corr,
    caption_hist,
    fmt,
    unit_note_for,
)
from app.pipeline.fielddict import FieldDictionary
from app.pipeline.reference import ReferenceRanges
from app.pipeline.stats import compare_groups, reference_bands

POINT_FIELDS = ("sample_index", "status", "deviation_pct", "pct")


def _points(long: pd.DataFrame, metric: str, limit: int) -> tuple[list[dict], bool]:
    """逐点精简载荷；超限则等距抽样并置 ``sampled=True``。

    判定长表里归一化位置列叫 ``pos``（区间位置 0–1），对外载荷里叫 ``pct``（8.1 的字段名），
    在**这一处**做改名，前端就不会出现两个名字。
    """
    if long.empty or "metric" not in long.columns:
        return [], False
    subset = long.loc[long["metric"] == metric]
    if subset.empty:
        return [], False
    available = [c for c in ("sample_index", "status", "deviation_pct", "pos") if c in subset.columns]
    rounded = subset[available].rename(columns={"pos": "pct"}).copy()
    for column in ("deviation_pct", "pct"):
        if column in rounded.columns:
            rounded[column] = rounded[column].map(lambda v: None if pd.isna(v) else round(float(v), 4))
    rows = rounded.to_dict("records")
    if len(rows) <= limit:
        return rows, False
    step = len(rows) / limit
    sampled = [rows[int(i * step)] for i in range(limit)]
    return sampled, True


def _decimals(fields: FieldDictionary, metric: str) -> int:
    return fields.decimals_of(metric)


def _meta(fields: FieldDictionary, metric: str) -> tuple[str, str]:
    spec = fields.spec(metric)
    return (spec.name_cn if spec else metric, spec.unit if spec else "")


def box_chart(
    frame: pd.DataFrame,
    long: pd.DataFrame,
    fields: FieldDictionary,
    ranges: ReferenceRanges,
    metric: str,
    *,
    settings: Settings | None = None,
    unit_log: list[str] | None = None,
) -> dict[str, Any]:
    """FR-09 箱线图：按性别分组，每组标注 n，叠加参考区间。"""
    settings = settings or get_settings()
    name_cn, unit = _meta(fields, metric)
    decimals = _decimals(fields, metric)

    groups: dict[str, dict[str, Any]] = {}
    categories: list[str] = []
    box_data: list[list[float] | None] = []
    has_gender = "gender" in frame.columns and frame["gender"].notna().any()

    buckets = [("male", "男"), ("female", "女")] if has_gender else [("all", "全部")]

    label_map = dict(buckets)
    for key, label in buckets:
        mask = (frame["gender"] == key) if key != "all" else pd.Series(True, index=frame.index)
        if metric in frame.columns:
            values = pd.to_numeric(frame.loc[mask, metric], errors="coerce").dropna()
        else:
            values = pd.Series(dtype=float)
        categories.append(label)
        if values.empty:
            box_data.append(None)
            groups[key] = {"n": 0, "mean": None, "median": None}
            continue
        q1, median, q3 = (float(values.quantile(q)) for q in (0.25, 0.5, 0.75))
        box_data.append([float(values.min()), q1, median, q3, float(values.max())])
        groups[key] = {"n": int(values.size), "mean": float(values.mean()), "median": median}

    gender_dependent, bands = reference_bands(metric, ranges)
    comparison = compare_groups(frame, metric) if has_gender else {"performed": False, "reason": "no_gender"}
    note = unit_note_for(metric, unit, unit, 1.0)
    for line in unit_log or []:
        if line.startswith(metric):
            note = "；" + line
    caption = caption_box(
        metric_cn=name_cn,
        unit=unit,
        groups={"male": groups.get("male", {}), "female": groups.get("female", {})} if has_gender else {},
        comparison=comparison,
        decimals=decimals,
        unit_note=note,
    )

    option: dict[str, Any] = {
        "title": {"text": f"{name_cn}（按性别分组）" if has_gender else f"{name_cn}（未按性别分组）"},
        "tooltip": {"trigger": "item"},
        "grid": {"left": 56, "right": 24, "top": 56, "bottom": 48},
        "xAxis": {"type": "category", "data": categories, "name": "分组"},
        "yAxis": {"type": "value", "name": unit, "scale": True},
        "series": [
            {
                "name": name_cn,
                "type": "boxplot",
                "data": box_data,
                "boxWidth": [12, 48],
                "label": {"show": True, "position": "top", "formatter": "{c}"},
            }
        ],
    }
    if bands:
        # 性别相关指标画两条区间（男/女），只画一条会让女性样本看起来集体偏低（BR-17）
        lines = []
        for band in bands:
            prefix = {"male": "男", "female": "女"}.get(band["gender"], "")
            style = {"type": "dashed" if band["gender"] != "female" else "dotted"}
            lines.append(
                {
                    "yAxis": band["low"],
                    "lineStyle": style,
                    "label": {"formatter": f"{prefix}下限 {fmt(band['low'], decimals)}"},
                }
            )
            lines.append(
                {
                    "yAxis": band["high"],
                    "lineStyle": style,
                    "label": {"formatter": f"{prefix}上限 {fmt(band['high'], decimals)}"},
                }
            )
        option["series"][0]["markLine"] = {
            "symbol": "none",
            "silent": True,
            "label": {"position": "insideEndTop"},
            "data": lines,
        }
    # 每组样本量标注（FR-09 要求"每组标注 n"）
    option["graphic"] = [
        {
            "type": "text",
            "left": "center",
            "bottom": 8,
            "style": {
                "text": " / ".join(f"{categories[i]} n={groups[buckets[i][0]]['n']}" for i in range(len(buckets))),
                "fontSize": 12,
            },
        }
    ]

    points, sampled = _points(long, metric, settings.points_limit)
    return {
        "kind": "box",
        "metric": metric,
        "title": name_cn,
        "unit": unit,
        "echarts_option": option,
        "points": points,
        "sampled": sampled,
        "caption": caption.text,
        "caption_branch": caption.branch,
        "supporting": {
            "groups": groups,
            "comparison": comparison,
            "reference_bands": bands,
            "gender_dependent": gender_dependent,
            "label_map": label_map,
        },
    }


def hist_chart(
    frame: pd.DataFrame,
    long: pd.DataFrame,
    fields: FieldDictionary,
    ranges: ReferenceRanges,
    metric: str,
    *,
    settings: Settings | None = None,
    bins: int = 20,
    unit_log: list[str] | None = None,
) -> dict[str, Any]:
    """FR-10 直方图：叠加参考区间线，并给出区间内外占比。"""
    settings = settings or get_settings()
    name_cn, unit = _meta(fields, metric)
    decimals = _decimals(fields, metric)
    if metric in frame.columns:
        values = pd.to_numeric(frame[metric], errors="coerce").dropna()
    else:
        values = pd.Series(dtype=float)

    gender_dependent, bands = reference_bands(metric, ranges)
    total = int(values.size)
    pct_normal = None
    labels: list[str] = []
    counts: list[int] = []
    if total:
        counts_array, edges = np.histogram(values.to_numpy(dtype=float), bins=bins)
        labels = [f"{fmt(edges[i], decimals)}–{fmt(edges[i + 1], decimals)}" for i in range(len(counts_array))]
        counts = [int(c) for c in counts_array]

    status_long = long.loc[long["metric"] == metric]
    shares = {
        status: round(float((status_long["status"] == status).mean()), 4) if len(status_long) else None
        for status in ("LOW", "NORMAL", "HIGH", "NA")
    }
    # 区间内占比必须按**每个样本自己的性别区间**算（BR-17）：直接拿一条区间套所有人，
    # 女性 HGB 会被大量算成"偏低"，这正是最容易被当成"发现"的假结论。
    if shares["NORMAL"] is not None:
        pct_normal = float(shares["NORMAL"])

    note = ""
    for line in unit_log or []:
        if line.startswith(metric):
            note = "；" + line
    bands_text = ""
    if gender_dependent:
        bands_text = " / ".join(
            f"{'男' if b['gender'] == 'male' else '女'} {fmt(b['low'], decimals)}–{fmt(b['high'], decimals)}"
            for b in bands
        )
    caption = caption_hist(
        metric_cn=name_cn,
        unit=unit,
        n=total,
        median=float(values.median()) if total else None,
        low=bands[0]["low"] if bands and not gender_dependent else None,
        high=bands[0]["high"] if bands and not gender_dependent else None,
        pct_normal=pct_normal,
        decimals=decimals,
        unit_note=note,
        bands_text=bands_text,
    )

    option: dict[str, Any] = {
        "title": {"text": f"{name_cn} 分布"},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 56, "right": 24, "top": 56, "bottom": 64},
        "xAxis": {"type": "category", "data": labels, "name": unit, "axisLabel": {"rotate": 40}},
        "yAxis": {"type": "value", "name": "样本数"},
        "series": [{"name": "样本数", "type": "bar", "data": counts, "barGap": "0%"}],
    }
    if bands and labels:
        lines = []
        for band in bands:
            prefix = {"male": "男", "female": "女"}.get(band["gender"], "")
            style = {"type": "dashed" if band["gender"] != "female" else "dotted"}
            lines.append(
                {
                    "xAxis": _nearest_label(labels, band["low"]),
                    "lineStyle": style,
                    "label": {"formatter": f"{prefix}下限 {fmt(band['low'], decimals)}"},
                }
            )
            lines.append(
                {
                    "xAxis": _nearest_label(labels, band["high"]),
                    "lineStyle": style,
                    "label": {"formatter": f"{prefix}上限 {fmt(band['high'], decimals)}"},
                }
            )
        option["series"][0]["markLine"] = {"symbol": "none", "silent": True, "data": lines}

    points, sampled = _points(long, metric, settings.points_limit)
    return {
        "kind": "hist",
        "metric": metric,
        "title": name_cn,
        "unit": unit,
        "echarts_option": option,
        "points": points,
        "sampled": sampled,
        "caption": caption.text,
        "caption_branch": caption.branch,
        "supporting": {
            "n": total,
            "median": float(values.median()) if total else None,
            "pct_normal": round(pct_normal, 4) if pct_normal is not None else None,
            "shares": shares,
            "reference_bands": bands,
            "gender_dependent": gender_dependent,
        },
    }


def _nearest_label(labels: list[str], value: float) -> str:
    """把参考边界落到最近的直方图柱上（markLine 的 xAxis 只接受类目名）。"""
    parsed = [(label, _first_number(label)) for label in labels]
    return min(parsed, key=lambda item: abs(item[1] - value))[0]


def _first_number(label: str) -> float:
    head = label.split("–")[0].replace("−", "-")
    try:
        return float(head)
    except ValueError:
        return 0.0


def corr_chart(
    frame: pd.DataFrame,
    fields: FieldDictionary,
    stats_payload: dict,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """FR-11 相关性热力图：Spearman，标出数学耦合的指标对（BR-12）。"""
    settings = settings or get_settings()
    metrics: list[str] = list(stats_payload.get("metrics") or [])
    matrix: dict[str, dict[str, float | None]] = stats_payload.get("matrix") or {}
    pairs: list[dict] = stats_payload.get("pairs") or []
    names = [_meta(fields, m)[0] for m in metrics]

    data: list[list[Any]] = []
    for i, a in enumerate(metrics):
        for j, b in enumerate(metrics):
            value = (matrix.get(a) or {}).get(b)
            if value is not None:
                data.append([j, i, round(float(value), 3)])

    option: dict[str, Any] = {
        "title": {"text": "指标相关性（Spearman）"},
        "tooltip": {"position": "top"},
        "grid": {"left": 110, "right": 24, "top": 64, "bottom": 110},
        "xAxis": {"type": "category", "data": names, "axisLabel": {"rotate": 40}},
        "yAxis": {"type": "category", "data": names},
        "visualMap": {"min": -1, "max": 1, "calculable": True, "orient": "horizontal", "left": "center", "bottom": 0},
        "series": [{"name": "rho", "type": "heatmap", "data": data}],
    }

    # 取耦合与最强非耦合各一条做图注（BR-12）
    coupled = next((p for p in pairs if p.get("coupling")), None)
    strongest = max(
        (p for p in pairs if not p.get("coupling")),
        key=lambda p: abs(p.get("rho") or 0.0),
        default=None,
    )
    sample = coupled or strongest
    if sample is None:
        caption = caption_corr(a="—", b="—", rho=None, n=len(metrics))
    else:
        caption = caption_corr(
            a=_meta(fields, str(sample["a"]))[0],
            b=_meta(fields, str(sample["b"]))[0],
            rho=sample.get("rho"),
            n=int(sample.get("n") or 0),
            coupling=bool(sample.get("coupling")),
        )

    return {
        "kind": "corr",
        "metric": None,
        "title": "相关性",
        "unit": "",
        "echarts_option": option,
        "points": [],
        "sampled": False,
        "caption": caption.text,
        "caption_branch": caption.branch,
        "supporting": {
            "method": stats_payload.get("method", "spearman"),
            "metrics": metrics,
            "notes": stats_payload.get("notes", []),
            "coupled_pairs": [p for p in pairs if p.get("coupling")],
        },
    }


def scatter_chart(
    frame: pd.DataFrame,
    fields: FieldDictionary,
    x_metric: str,
    y_metric: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """FR-12 散点图：两个指标的关系，点按 y 轴指标的三态着色（颜色由前端主题注入）。

    与箱线图不同，散点图的点位必须带原始坐标，否则画不出来——这是 ``points[]``
    四标量白名单的唯一例外，因此这里单独用 ``pair`` 字段名，避免被误当成通用载荷。
    """
    from app.pipeline.stats import correlation

    settings = settings or get_settings()
    x_name, x_unit = _meta(fields, x_metric)
    y_name, y_unit = _meta(fields, y_metric)

    columns = [c for c in (x_metric, y_metric) if c in frame.columns]
    if len(columns) < 2:
        pairs_df = pd.DataFrame(columns=[x_metric, y_metric, "sample_index"])
    else:
        pairs_df = frame[[x_metric, y_metric] + (["sample_index"] if "sample_index" in frame else [])].copy()
        pairs_df[x_metric] = pd.to_numeric(pairs_df[x_metric], errors="coerce")
        pairs_df[y_metric] = pd.to_numeric(pairs_df[y_metric], errors="coerce")
        pairs_df = pairs_df.dropna(subset=[x_metric, y_metric])

    rho = None
    if len(pairs_df) >= 3:
        rho = correlation(pairs_df[[x_metric, y_metric]], fields).get("matrix", {}).get(y_metric, {}).get(x_metric)
    caption = caption_corr(a=x_name, b=y_name, rho=rho, n=len(pairs_df))

    data = [
        [
            round(float(row[x_metric]), 4),
            round(float(row[y_metric]), 4),
            int(row["sample_index"]) if "sample_index" in pairs_df.columns else None,
        ]
        for _, row in pairs_df.iterrows()
    ]
    sampled = False
    if len(data) > settings.points_limit:
        step = len(data) / settings.points_limit
        data = [data[int(i * step)] for i in range(settings.points_limit)]
        sampled = True

    option: dict[str, Any] = {
        "title": {"text": f"{x_name} 与 {y_name}"},
        "tooltip": {"trigger": "item"},
        "grid": {"left": 64, "right": 24, "top": 56, "bottom": 56},
        "xAxis": {"type": "value", "name": f"{x_name}（{x_unit}）", "scale": True},
        "yAxis": {"type": "value", "name": f"{y_name}（{y_unit}）", "scale": True},
        "series": [
            {
                "name": f"{x_name}-{y_name}",
                "type": "scatter",
                "symbolSize": 6,
                "data": data,
            }
        ],
    }

    return {
        "kind": "scatter",
        "metric": y_metric,
        "title": f"{x_name} 与 {y_name}",
        "unit": y_unit,
        "echarts_option": option,
        "points": [{"pair": [d[0], d[1]], "sample_index": d[2]} for d in data],
        "sampled": sampled,
        "caption": caption.text,
        "caption_branch": caption.branch,
        "supporting": {"x": x_metric, "y": y_metric, "n": len(pairs_df), "rho": rho, "unit_y": y_unit},
    }
