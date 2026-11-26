"""S7 统计（SRS FR-07、FR-08、FR-30、BR-08、BR-10、BR-11）。

三条口径必须写死在代码里，否则自动文案会产出"看起来合理"的错结论：

* 相关默认 **Spearman**，且 ``|ρ| < 0.3`` 一律标 ``不作解读``（BR-10）；
* 组间检验用 **Mann-Whitney U**，任一组 ``n < 10`` 时**不检验、不返回 p 值**（BR-11 / BR-16）；
* 三档占比来自 S6 的判定结果，**不是**本模块重新算的，保证图、表、文案同源。

``MCH = HGB / RBC`` 这类恒等式会让相关系数天然接近 1，因此成对结果必须带
``coupling`` 标记（BR-12），前端据此在热力图上标注"数学耦合"。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.pipeline.fielddict import FieldDictionary
from app.pipeline.reference import MetricStatus

MIN_GROUP_N = 10
WEAK_RHO = 0.30
MAX_DEVIATION_DISPLAY = 999.0
"""展示层偏离度上限（百分比）。窄区间上偏离度可以到四位数，原样显示像是 bug。"""

# BR-12：定义性相关（不是"发现"，是恒等式）
DEFINED_COUPLINGS: dict[frozenset[str], str] = {
    frozenset({"mch", "hgb"}): "mch = hgb / rbc",
    frozenset({"mch", "rbc"}): "mch = hgb / rbc",
    frozenset({"mchc", "hgb"}): "mchc = hgb / hct",
    frozenset({"mchc", "hct"}): "mchc = hgb / hct",
    frozenset({"hct", "rbc"}): "hct ≈ rbc × mcv / 10",
    frozenset({"hct", "mcv"}): "hct ≈ rbc × mcv / 10",
}


def coupling_of(a: str, b: str) -> str | None:
    return DEFINED_COUPLINGS.get(frozenset({a, b}))


def _status_shares(long: pd.DataFrame, metric: str, total: int) -> dict[str, float]:
    rows = long[long["metric"] == metric]
    if not total:
        return {"pct_low": 0.0, "pct_normal": 0.0, "pct_above": 0.0, "pct_na": 0.0}
    counts = rows["status"].value_counts()
    return {
        "pct_low": round(float(counts.get(MetricStatus.LOW.value, 0)) / total, 4),
        "pct_normal": round(float(counts.get(MetricStatus.NORMAL.value, 0)) / total, 4),
        "pct_above": round(float(counts.get(MetricStatus.HIGH.value, 0)) / total, 4),
        "pct_na": round(float(counts.get(MetricStatus.NA.value, 0)) / total, 4),
    }


def reference_bands(metric: str, ranges) -> tuple[bool, list[dict]]:
    """返回 ``(是否性别相关, [{gender, low, high}])``。

    **性别相关指标不能只给一条区间**：HGB 男 130–175、女 115–150，若界面上只显示男区间，
    女性样本会被大量判成"偏低"——这正是 BR-17 与 RK-01 要防的误读。所以这里把两条都交出去，
    由界面显式标注"男 130–175 / 女 115–150"，而不是悄悄挑一条。
    """
    if ranges is None:
        return False, []
    if getattr(ranges, "gender_dependent", lambda _m: False)(metric):
        bands = []
        for gender in ("male", "female"):
            interval = ranges.interval(metric, gender)
            if interval is not None:
                bands.append({"gender": gender, "low": interval.low, "high": interval.high})
        return True, bands
    interval = ranges.interval(metric)
    if interval is None:
        return False, []
    return False, [{"gender": "all", "low": interval.low, "high": interval.high}]


def metric_overview(
    frame: pd.DataFrame, long: pd.DataFrame, fields: FieldDictionary, *, ranges=None, unified: bool = False
) -> list[dict]:
    """FR-30 指标状态总览：一个指标一行，含三档占比与最大偏离。

    ``unified=True``（数据集无 gender、用户显式声明按统一区间判定）时，性别相关指标
    也会给出 ``low/high``——取自长表里实际参与判定的那条统一区间，并把 ``ri_source``
    标成 ``unified``，让界面能显示"本数据集按统一区间判定"的说明。
    """
    total = len(frame)
    items: list[dict] = []
    for metric in fields.display_order:
        spec = fields.spec(metric)
        if spec is None or not spec.is_metric or metric not in frame.columns:
            continue
        series = pd.to_numeric(frame[metric], errors="coerce")
        # BR-21：填充出来的格子不算实测值——统计量（均值/中位数/四分位/极值）只用实测值，
        # 否则"缺 10% 的数据"会被中位数悄悄补成一个看起来更漂亮的分布。
        metric_rows = long.loc[long["metric"] == metric] if len(long) else long
        imputed_rows = metric_rows.loc[metric_rows["reason"] == "imputed"] if len(metric_rows) else metric_rows
        n_imputed = int(len(imputed_rows))
        if n_imputed and "sample_index" in frame.columns:
            filled_samples = set(imputed_rows["sample_index"].tolist())
            keep = ~frame["sample_index"].isin(filled_samples)
            series = series.where(keep)
        valid = series.dropna()
        deviation = long.loc[long["metric"] == metric, "deviation_pct"]
        raw_max_dev = float(deviation.max()) if len(deviation) else 0.0
        # 窄区间会把偏离度放大到四位数（baso_pct 区间宽 1，一个 34.4% 就是 3440%）。
        # 数字本身没错，但"最大偏离 3440%"读起来像 bug，所以展示层封顶并用 ≥ 表达；
        # 原始值仍然给出，报告与排查要用它。
        max_dev_capped = raw_max_dev > MAX_DEVIATION_DISPLAY
        max_dev = min(raw_max_dev, MAX_DEVIATION_DISPLAY)
        gender_dependent, bands = reference_bands(metric, ranges)
        low = bands[0]["low"] if bands and not gender_dependent else None
        high = bands[0]["high"] if bands and not gender_dependent else None
        ri_source = "default"
        if unified and gender_dependent:
            rows = long[long["metric"] == metric]
            if "low" in rows.columns and rows["low"].notna().any():
                indexed = rows.dropna(subset=["low"])
                low = float(indexed["low"].iloc[0])
                high = float(indexed["high"].iloc[0])
            ri_source = "unified"
        items.append(
            {
                "metric": metric,
                "name_cn": spec.name_cn,
                "unit": spec.unit,
                "decimals": fields.decimals_of(metric),
                "n": int(valid.size),
                "n_observed": int(valid.size),
                "n_imputed": n_imputed,
                "missing": int(series.isna().sum()),
                "mean": _f(valid.mean()),
                "std": _f(valid.std(ddof=1)),
                "median": _f(valid.median()),
                "q1": _f(valid.quantile(0.25)),
                "q3": _f(valid.quantile(0.75)),
                "min": _f(valid.min()),
                "max": _f(valid.max()),
                "low": low,
                "high": high,
                "gender_dependent": gender_dependent,
                "ranges_by_gender": bands,
                "ri_source": ri_source,
                "max_deviation_pct": round(max_dev, 2),
                "max_deviation_pct_raw": round(raw_max_dev, 2),
                "max_deviation_capped": max_dev_capped,
                **_status_shares(long, metric, total),
            }
        )
    return items


def group_overview(
    frame: pd.DataFrame, long: pd.DataFrame, fields: FieldDictionary, *, by: str = "gender"
) -> list[dict]:
    """FR-08 分组统计：按 ``gender`` / ``age_band`` 分组，每组每个指标一行。"""
    if by not in frame.columns:
        return []
    rows: list[dict] = []
    for group_value, group_frame in frame.groupby(by, dropna=False):
        indexes = {int(i) for i in group_frame["sample_index"]} if "sample_index" in group_frame else set()
        group_long = long[long["sample_index"].isin(indexes)] if indexes else long.iloc[0:0]
        total = len(group_frame)
        for metric in fields.metric_fields():
            if metric not in group_frame.columns:
                continue
            series = pd.to_numeric(group_frame[metric], errors="coerce")
            valid = series.dropna()
            if valid.empty:
                continue
            rows.append(
                {
                    "group_by": by,
                    "group": str(group_value),
                    "metric": metric,
                    "name_cn": fields.name_cn(metric),
                    "unit": fields.unit(metric),
                    "n": int(valid.size),
                    "mean": _f(valid.mean()),
                    "std": _f(valid.std(ddof=1)),
                    "median": _f(valid.median()),
                    "q1": _f(valid.quantile(0.25)),
                    "q3": _f(valid.quantile(0.75)),
                    "min": _f(valid.min()),
                    "max": _f(valid.max()),
                    **_status_shares(group_long, metric, total),
                }
            )
    return rows


def correlation(
    frame: pd.DataFrame, fields: FieldDictionary, *, method: str = "spearman"
) -> dict:
    """FR-11 相关性矩阵 + 成对明细（含耦合标注与弱相关标注）。"""
    metrics = [m for m in fields.metric_fields() if m in frame.columns]
    usable = [m for m in metrics if pd.to_numeric(frame[m], errors="coerce").notna().sum() >= 3]
    if len(usable) < 2:
        return {"method": method, "metrics": usable, "matrix": {}, "pairs": [], "notes": ["可参与相关的指标不足 2 个"]}

    numeric = frame[usable].apply(pd.to_numeric, errors="coerce")
    matrix = numeric.corr(method="pearson") if method == "pearson" else numeric.corr(method="spearman")

    pairs: list[dict] = []
    for i, a in enumerate(usable):
        for b in usable[i + 1 :]:
            sub = numeric[[a, b]].dropna()
            rho = matrix.loc[a, b]
            p_value = None
            if len(sub) >= 3:
                if method == "pearson":
                    _r, p_value = sps.pearsonr(sub[a], sub[b])
                else:
                    _r, p_value = sps.spearmanr(sub[a], sub[b])
            coupling = coupling_of(a, b)
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "rho": _f(rho),
                    "p": _f(p_value),
                    "n": int(len(sub)),
                    "coupling": coupling,
                    "weak": bool(abs(rho) < WEAK_RHO),
                    # BR-16：|ρ| < 0.3 不给解读
                    "interpretable": bool(coupling is None and abs(rho) >= WEAK_RHO),
                }
            )

    notes: list[str] = []
    if any(p["coupling"] for p in pairs):
        notes.append("标有数学耦合的指标对由定义决定，不构成独立发现")
    if any(p["weak"] for p in pairs):
        notes.append(f"|ρ| < {WEAK_RHO} 的指标对不作解读")
    return {
        "method": method,
        "metrics": usable,
        "matrix": {a: {b: _f(matrix.loc[a, b]) for b in usable} for a in usable},
        "pairs": pairs,
        "notes": notes,
    }


def compare_groups(frame: pd.DataFrame, metric: str, *, group: str = "gender") -> dict:
    """BR-11：男女两组 Mann-Whitney U。任一组 n < 10 → 不检验、响应体不含 p 值。"""
    if group not in frame.columns or metric not in frame.columns:
        return {"performed": False, "reason": "missing_column"}
    series = pd.to_numeric(frame[metric], errors="coerce")
    male = series[frame[group] == "male"].dropna()
    female = series[frame[group] == "female"].dropna()
    n_male, n_female = int(male.size), int(female.size)

    if n_male < MIN_GROUP_N or n_female < MIN_GROUP_N:
        return {
            "performed": False,
            "reason": "small_n",
            "metric": metric,
            "n_male": n_male,
            "n_female": n_female,
            "small_group": "male" if n_male < MIN_GROUP_N else "female",
            "n_small": min(n_male, n_female),
        }

    result = sps.mannwhitneyu(male, female, alternative="two-sided")
    return {
        "performed": True,
        "metric": metric,
        "n_male": n_male,
        "n_female": n_female,
        "u": float(result.statistic),
        "p": float(result.pvalue),
        "p_ge_005": bool(result.pvalue >= 0.05),
    }


def _f(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return round(number, 4)
