"""FR-09/10/11 图表配置生成（ECharts option + 点位载荷 + 一句话结论）。

三条约束决定了这里的写法：

1. **不返回颜色**。option 里只出现语义（"偏高/正常/偏低"），颜色由前端 ECharts 主题
   按 ``theme/tokens.json`` 注入（NFR-M-07）。后端返回十六进制色值的那一刻，
   屏幕图与报告图就开始各自漂移（RK-22）。
2. **不返回宽表**。点位载荷 ``points[]`` 只有 4 个标量，≤ 2000 点（NFR-P-09 / RK-21）。
3. **图、点位、文案由同一次计算产出**（8.1 关于图表接口的三样产出）。
"""

from __future__ import annotations

import math
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

OUTLIER_CAP = 200
"""箱线图离群点最多画多少个。

嗜碱性粒细胞百分比这类指标在 9.6 万行里能挑出上千个离群点，全画出来既卡又看不清。
超出就等距抽样（与 ``points[]`` 同一套理由），真实个数留在 ``supporting.outliers``。"""

HIST_ZERO_SHARE = 0.25
"""零值占比达到这个比例就单独给"0"一个桶。

``baso_pct`` 有 96% 的样本恰好等于 0，剩下 4% 拖到 34%——等宽 20 桶铺满 0–34 时，
第一桶吃掉 9.2 万条、后面 19 桶全是空的，图等于没画。"""

HIST_FENCE = 3.0
"""直方图显示窗口的边界系数：超过 ``Q3 + 3×IQR`` 的长尾不画进主图。

用 3×IQR（而不是 99.5 分位）作判据，是因为分位数在**小样本**上会自己跟着极值跑：
36 个非零值里有 1 个 34%，p99.5 仍然是 34，等于没裁。3×IQR 是固定的"远界"，
对 10 行的夹具和 9.6 万行的真实数据给出的是同一套语义。窗口外的样本不会被丢弃，
而是单独计数并写在副标题里。"""


def _display_value(value: float) -> float:
    """把"几乎是 0"的浮点噪声（如 5.4e-79）显示成 0。

    这类值来自原始仪器的极小量，放进坐标轴只会让刻度变成 ``5.4e-79``，
    读者什么也得不到；它在判定里本来就是"接近 0"，显示成 0 不损失信息。
    """
    if value != 0 and abs(value) < 1e-9:
        return 0.0
    return float(value)


def _nice_bound(value: float, *, up: bool) -> float:
    """把坐标轴边界收成整一点的数（2.496 → 2.5，204.2 → 210）。

    边界由数据算出，直接给 ECharts 会得到 "2.496" 这种刻度标签：数字没错，
    但读者第一眼会去找"2.496 是什么规定值"。轴边界只是画布范围，不是结论。
    """
    if value == 0:
        return 0.0
    step = 10 ** (math.floor(math.log10(abs(value))) - 1)
    scaled = value / step
    return (math.ceil(scaled) if up else math.floor(scaled)) * step


def _box_stats(values: pd.Series) -> tuple[list[float], list[float]]:
    """返回 ``(五元组, 离群值列表)``，须端用 Tukey 的 1.5×IQR，而不是 min/max。

    原来须端直接取最小/最大值，结果是**一个**极端值就能把 y 轴拉满、箱体（Q1–Q3）
    被压成一条线——图看着像坏了，其实是须端定义选错了。离群值不丢弃：
    它们往往是这份数据里最值得看的样本（BR-06），只是改用散点单独呈现。
    """
    q1, median, q3 = (float(values.quantile(q)) for q in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    fence_low = q1 - 1.5 * iqr
    fence_high = q3 + 1.5 * iqr
    inside = values[(values >= fence_low) & (values <= fence_high)]
    # IQR = 0（例如全组都是 0）时 inside 可能为空，退化为四分位本身，须长为 0
    whisker_low = _display_value(float(inside.min()) if not inside.empty else q1)
    whisker_high = _display_value(float(inside.max()) if not inside.empty else q3)
    outliers = [_display_value(float(v)) for v in values[(values < fence_low) | (values > fence_high)].tolist()]
    return [
        _display_value(whisker_low),
        _display_value(q1),
        _display_value(median),
        _display_value(q3),
        whisker_high,
    ], outliers


def _thin(values: list[float], cap: int = OUTLIER_CAP) -> list[float]:
    if len(values) <= cap:
        return values
    step = len(values) / cap
    return [values[int(i * step)] for i in range(cap)]


def _hist_bins(values: np.ndarray, bins: int, decimals: int = 2) -> dict[str, Any]:
    """稳健分箱：零值堆积单独一桶，长尾用分位窗口收住，窗口外的量单独计数。

    返回 ``labels / counts / window / outside_count / outside_max / zero_bucket``。
    """
    if values.size == 0:
        return {
            "labels": [],
            "counts": [],
            "window": None,
            "outside_count": 0,
            "outside_max": None,
            "zero_bucket": False,
        }

    zero_share = float((values == 0).mean())
    zero_bucket = zero_share >= HIST_ZERO_SHARE and bool((values != 0).any())
    body = values[values != 0] if zero_bucket else values
    if body.size == 0:
        body = values

    body_min = float(body.min())
    body_max = float(body.max())
    q1, q3 = float(np.percentile(body, 25)), float(np.percentile(body, 75))
    iqr = q3 - q1
    far_high = q3 + HIST_FENCE * iqr
    far_low = q1 - HIST_FENCE * iqr

    # 只有尾部长到"远超主体"时才收窗（max > Q3+3IQR）；否则小样本会被无谓地切掉两端，
    # 桶里合计少两条——"图没错、数字少了"比图不好看严重得多。
    high = far_high if body_max > far_high else body_max
    low = body_min if (zero_bucket or body_min >= far_low) else far_low
    high = max(high, low)
    if high <= low:
        # 全部取值相同（例如全组都是 0.6）时给一个可画的窄窗，避免 np.histogram 报错
        high = low + max(abs(low) * 0.1, 1.0)

    kept = body[(body >= low) & (body <= high)]
    counts_array, edges = np.histogram(kept, bins=bins, range=(low, high))
    # 窗口外的样本：> high 的全部算"超出显示范围"（低端在非零桶情况下才可能漏）
    outside = values[values > high]
    if not zero_bucket:
        outside = values[(values > high) | (values < low)]

    labels = [
        f"{fmt(float(edges[i]), decimals)}–{fmt(float(edges[i + 1]), decimals)}"
        for i in range(len(counts_array))
    ]
    counts = [int(c) for c in counts_array]
    if zero_bucket:
        zero_label = "0" if low > 0 else f"≤{fmt(float(edges[0]), decimals)}"
        labels = [zero_label, *labels]
        counts = [int((values == 0).sum()), *counts]

    return {
        "labels": labels,
        "counts": counts,
        "window": (low, high),
        "outside_count": int(outside.size),
        "outside_max": float(values.max()) if outside.size else None,
        "zero_bucket": zero_bucket,
    }



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
    outliers_by_group: dict[str, list[float]] = {}
    for _position, (key, label) in enumerate(buckets):
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
        five, outliers = _box_stats(values)
        box_data.append(five)
        # 离群点画成散点：一个 34% 的嗜碱粒细胞值不该把整条 y 轴拉满，
        # 但也不该消失——它恰恰是这份数据里最该被看见的样本（BR-06）
        outliers_by_group[key] = outliers
        q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
        iqr = q3 - q1
        # IQR 为 0（主体全相同）时 3×IQR 退化成 0，会把整组裁成一条线；
        # 这种分布本来就没有"远界"可言，直接用真实极值当窗口
        window_low = float(values.min()) if iqr <= 0 else max(float(values.min()), q1 - HIST_FENCE * iqr)
        window_high = float(values.max()) if iqr <= 0 else min(float(values.max()), q3 + HIST_FENCE * iqr)
        groups[key] = {
            "n": int(values.size),
            "mean": float(values.mean()),
            "median": five[2],
            "whisker_low": five[0],
            "whisker_high": five[4],
            "outliers": len(outliers),
            # 显示窗口的候选上/下界：Q3±3×IQR 与真实极值取交集——和直方图用同一把尺子，
            # 图与图之间才不会一个显示到 35、另一个显示到 3（HIST_FENCE）
            "window_low": _display_value(window_low),
            "window_high": _display_value(window_high),
        }

    gender_dependent, bands = reference_bands(metric, ranges)
    comparison = compare_groups(frame, metric) if has_gender else {"performed": False, "reason": "no_gender"}
    note = unit_note_for(metric, unit, unit, 1.0)
    for line in unit_log or []:
        if line.startswith(metric):
            note = "；" + line
    # 数据集无性别、且用户显式声明按统一区间判定（FR-16）：图上与文案都必须说明，
    # 不能沿用"按性别各自参考区间"的句式，否则读到的人会以为系统知道性别
    unified = "ri_source" in long.columns and bool((long["ri_source"] == "unified").any())
    unified_bands = None
    if unified and gender_dependent:
        # 注意不能用 ranges.interval(metric)：它等价于 resolve(metric, None)，
        # 在 BR-17 下会返回 None。统一区间就是配置里的 default。
        effective = ranges.default.get(metric)
        if effective is not None:
            unified_bands = (effective.low, effective.high)
    caption = caption_box(
        metric_cn=name_cn,
        unit=unit,
        groups=(
            {"male": groups.get("male", {}), "female": groups.get("female", {})}
            if has_gender
            else {"all": groups.get("all", {})}
        ),
        comparison=comparison,
        decimals=decimals,
        unit_note=note,
        unified_bands=unified_bands,
    )

    option: dict[str, Any] = {
        "title": {"text": f"{name_cn}（按性别分组）" if has_gender else f"{name_cn}（未按性别分组）"},
        "tooltip": {"trigger": "item"},
        "grid": {"left": 56, "right": 24, "top": 76, "bottom": 48},
        "xAxis": {"type": "category", "data": categories, "name": "分组", "nameLocation": "middle", "nameGap": 28},
        "yAxis": {"type": "value", "name": unit, "scale": True, "nameLocation": "end", "nameGap": 14},
        "series": [
            {
                "name": name_cn,
                "type": "boxplot",
                "data": box_data,
                "boxWidth": [12, 48],
                # 不显示 {c}：boxplot 的标签是整个五元组，画出来是"0,0,0.6,1,34"这种噪声
                "label": {"show": False},
            }
        ],
    }

    # 显示窗口：上界取 Q3+3×IQR（与直方图同一把尺子），比须端宽、比极值窄。
    # 比须端宽是为了让"略超须端"的离群点也画得出来（只报数不画点，读者会怀疑图被裁过）；
    # 比极值窄是为了不让一个 34% 的值把箱体重新压成一条线。
    totals = [group for group in groups.values() if group.get("window_high") is not None]
    all_outliers = [value for values in outliers_by_group.values() for value in values]
    axis_min: float | None = None
    axis_max: float | None = None
    if totals:
        low_window = min(group["window_low"] for group in totals)
        high_window = max(group["window_high"] for group in totals)
        span = high_window - low_window or max(abs(high_window) * 0.1, 1.0)
        # 数据本来就贴近 0 时（百分比类指标）轴从 0 起，否则按窗口留一点边距
        axis_min = 0.0 if 0 <= low_window <= span * 0.25 else _nice_bound(low_window - span * 0.04, up=False)
        axis_max = _nice_bound(high_window + span * 0.04, up=True)
        option["yAxis"]["min"] = axis_min
        option["yAxis"]["max"] = axis_max

    outlier_points: list[list[float]] = []
    hidden = 0
    drawn = 0
    for position, (key, _label) in enumerate(buckets):
        values = outliers_by_group.get(key, [])
        lower = axis_min if axis_min is not None else min(values, default=0.0)
        upper = axis_max if axis_max is not None else max(values, default=0.0)
        visible = [value for value in values if lower <= value <= upper]
        hidden += len(values) - len(visible)
        thinned = _thin(visible)
        drawn += len(thinned)
        outlier_points.extend([position, value] for value in thinned)

    total_outliers = sum(len(values) for values in outliers_by_group.values())
    if total_outliers:
        # 副标题交代"须只到 1.5 IQR，外面还有 N 个点"，否则读者会以为数据只到须端
        detail = " / ".join(
            f"{label} {len(outliers_by_group.get(key, []))}" for key, label in buckets if outliers_by_group.get(key)
        )
        note = f"须端为 1.5×IQR 内的最远值；离群点 {total_outliers} 个（{detail}）"
        if hidden:
            note += f"，其中 {hidden} 个超出显示范围未画出（最大 {fmt(max(all_outliers), decimals)}）"
        if drawn > OUTLIER_CAP and not hidden:
            note += "，仅显示前 200 个"
        option["title"]["subtext"] = note
        if outlier_points:
            option["series"].append(
                {
                    "name": "离群点",
                    "type": "scatter",
                    "data": outlier_points,
                    "symbolSize": 5,
                    "itemStyle": {"opacity": 0.6},
                    "tooltip": {"formatter": "{c}"},
                }
            )
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
    # 5.4e-79 这类浮点噪声会让桶标签变成"0–1e-08"，显示成 0 无损信息
    numeric = values.to_numpy(dtype=float)
    raw = np.where((numeric != 0) & (np.abs(numeric) < 1e-9), 0.0, numeric)
    pct_normal = None
    bucket = _hist_bins(raw, bins, decimals) if total else None
    labels = list(bucket["labels"]) if bucket else []
    counts = list(bucket["counts"]) if bucket else []

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
    # 无性别 + 统一区间：文案改口径，不再说"按性别各自判定"（FR-16）
    unified = "ri_source" in long.columns and bool((long["ri_source"] == "unified").any())
    # 统一区间 = 配置里的 default（不能用 ranges.interval(metric)，那等价于性别未知 → None）
    effective = ranges.default.get(metric) if ranges is not None else None
    caption = caption_hist(
        metric_cn=name_cn,
        unit=unit,
        n=total,
        median=float(values.median()) if total else None,
        low=(
            effective.low
            if unified and effective is not None
            else (bands[0]["low"] if bands and not gender_dependent else None)
        ),
        high=(
            effective.high
            if unified and effective is not None
            else (bands[0]["high"] if bands and not gender_dependent else None)
        ),
        pct_normal=pct_normal,
        decimals=decimals,
        unit_note=note,
        bands_text=bands_text,
        unified=unified and gender_dependent,
    )

    option: dict[str, Any] = {
        # top 留到 84：副标题可能是一整句话（"显示 0–2.3（覆盖 98.9%），另有 1,010 条…"），
        # 留窄了它会压到 y 轴最高刻度上，看起来像刻度值丢了
        "title": {"text": f"{name_cn} 分布", "top": 0},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 72, "right": 24, "top": 84, "bottom": 64},
        "xAxis": {
            "type": "category",
            "data": labels,
            "name": unit,
            "nameLocation": "middle",
            "nameGap": 52,
            "axisLabel": {"rotate": 45, "interval": "auto", "fontSize": 10, "hideOverlap": True},
        },
        "yAxis": {"type": "value", "name": "样本数", "nameLocation": "middle", "nameGap": 56},
        "series": [{"name": "样本数", "type": "bar", "data": counts, "barGap": "0%"}],
    }
    if bucket and bucket["window"] is not None:
        # 副标题必须写清"这根轴只画到哪"：窗口外的样本没被删，只是没画，
        # 不写出来读者会以为最大值就是窗口上界（这正是"重尾指标看着没异常"的由来）
        low_edge, high_edge = bucket["window"]
        coverage = (1 - bucket["outside_count"] / values.size) * 100 if values.size else 100.0
        parts = [f"显示 {fmt(low_edge, decimals)}–{fmt(high_edge, decimals)}（覆盖 {coverage:.1f}%）"]
        if bucket["zero_bucket"]:
            parts.append("0 值单列一桶")
        if bucket["outside_count"]:
            parts.append(
                f"另有 {bucket['outside_count']:,} 条超出显示范围（最大 {fmt(bucket['outside_max'], decimals)}）"
            )
        option["title"]["subtext"] = "，".join(parts)
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
            # 分箱策略也一并回传：报告与页面用同一份数字，测试也能直接断言窗口有没有生效
            "bins": {
                "labels": labels,
                "counts": counts,
                "window": list(bucket["window"]) if bucket and bucket["window"] else None,
                "outside_count": bucket["outside_count"] if bucket else 0,
                "outside_max": bucket["outside_max"] if bucket else None,
                "zero_bucket": bucket["zero_bucket"] if bucket else False,
            },
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


def _short_label(metric: str) -> str:
    """热力图轴标签用短代码（HGB / NEUT%），中文全名留给 tooltip 与导出。

    长中文名（"平均红细胞血红蛋白浓度"）在 N×N 的方格里无论怎么转都挤，
    而指标代码本身是这行的通用语言，短名反而更可读（4.4.5 的图注里已有全名）。
    """
    known = {
        "neut_pct": "NEUT%",
        "lymph_pct": "LYMPH%",
        "mono_pct": "MONO%",
        "eo_pct": "EO%",
        "baso_pct": "BASO%",
    }
    return known.get(metric, metric.upper())


def corr_chart(
    frame: pd.DataFrame,
    fields: FieldDictionary,
    stats_payload: dict,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """FR-11 相关性热力图：Spearman，标出数学耦合的指标对（BR-12）。

    呈现要点（v1.6 修补）：**方格子** + 短标签 + 格内写 ρ。
    格子宽扁是因为 grid 用了固定的 left/right/bottom 像素而容器变宽——宽度涨、高度不涨，
    方格子因此被拉成扁格子。这里改成"先按指标个数算格子边长，再由边长反推正方形绘制区"，
    容器变宽时整体居中，格子永远是正方形。
    """
    settings = settings or get_settings()
    metrics: list[str] = list(stats_payload.get("metrics") or [])
    matrix: dict[str, dict[str, float | None]] = stats_payload.get("matrix") or {}
    pairs: list[dict] = stats_payload.get("pairs") or []
    short = [_short_label(m) for m in metrics]
    names = [_meta(fields, m)[0] for m in metrics]

    count = max(len(metrics), 1)
    cell_px = max(22, min(44, 420 // count))  # 指标多则缩小格子，绘制区不超过 420 px
    plot_px = cell_px * count
    label_px = 11 if cell_px >= 34 else (9 if cell_px >= 26 else 8)

    data: list[dict[str, Any]] = []
    for i, a in enumerate(metrics):
        for j, b in enumerate(metrics):
            value = (matrix.get(a) or {}).get(b)
            if value is None:
                continue
            rho = round(float(value), 2)
            item: dict[str, Any] = {"value": [j, i, rho]}
            # 对角线恒为 1，写出来只是噪声；空格子代表"该指标无数据"，两者要能区分
            item["label"] = {"show": False} if a == b else {"formatter": f"{rho:.2f}"}
            data.append(item)

    option: dict[str, Any] = {
        "title": {
            "text": "指标相关性（Spearman）",
            "subtext": "格内为 ρ；对角线恒为 1，已隐去；空白格表示该指标无数据",
            "subtextStyle": {"fontSize": 11},
        },
        "tooltip": {"position": "top"},
        "grid": {"left": "center", "top": 64, "width": plot_px, "height": plot_px, "containLabel": False},
        "xAxis": {
            "type": "category",
            "data": short,
            "splitArea": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {"interval": 0, "fontSize": 11, "rotate": 0},
        },
        "yAxis": {
            "type": "category",
            "data": short,
            "inverse": True,
            "splitArea": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {"interval": 0, "fontSize": 11},
        },
        "visualMap": {
            "min": -1,
            "max": 1,
            "precision": 1,
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": 0,
        },
        "series": [
            {
                "name": "rho",
                "type": "heatmap",
                "data": data,
                "label": {"show": True, "fontSize": label_px},
                # borderColor 用 "transparent" 关键字而不是具体色值：缝隙透出卡片底色，
                # 既实现"白描边"的观感，又不让后端产出字面色值（NFR-M-07）
                "itemStyle": {"borderWidth": 2, "borderColor": "transparent"},
                "emphasis": {"itemStyle": {"borderWidth": 2, "borderColor": "transparent"}},
            }
        ],
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
            "labels": dict(zip(metrics, short, strict=False)),
            "full_names": dict(zip(metrics, names, strict=False)),
            "cell_px": cell_px,
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
