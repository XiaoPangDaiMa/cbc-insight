"""S6 判定（SRS FR-16、FR-17、BR-07、BR-08、BR-17、5.1 模式表）。

这一层只做两件事，且都必须可单测：

* 逐指标与**闭区间**比较，产出 ``HIGH / NORMAL / LOW / NA`` 四态；
* 把"受影响指标集合"映射到 5.1 的预设模式，并按 BR-08 算严重度。

不在这里做的事同样重要：**不输出任何诊断或疾病名称**（1.3 范围外、E-03 免责），
所以模式的中文名一律带"倾向"二字，且只描述"哪几项超出区间"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from app.pipeline.reference import Interval, MetricStatus, ReferenceRanges

CORE_METRICS: tuple[str, ...] = ("hgb", "rbc", "wbc", "plt", "hct", "mcv", "mch", "mchc")


class Pattern(StrEnum):
    """5.1 异常模式表的可执行版本。"""

    MICRO_HYPO = "MICRO_HYPO"
    MICRO = "MICRO"
    MACRO = "MACRO"
    ANEMIA = "ANEMIA"
    POLYCYTHEMIA_SUSPECT = "POLYCYTHEMIA_SUSPECT"
    THROMBOCYTOPENIA = "THROMBOCYTOPENIA"
    THROMBOCYTOSIS = "THROMBOCYTOSIS"
    LEUKOCYTOSIS = "LEUKOCYTOSIS"
    LEUKOPENIA = "LEUKOPENIA"
    MULTI_ABNORMAL = "MULTI_ABNORMAL"
    NORMAL = "NORMAL"
    # 5.1 的兜底缺口（1–2 项异常但匹配不上任何模式）：待 v1.6 补入 5.1 表
    UNCLASSIFIED = "UNCLASSIFIED"

    @property
    def text_cn(self) -> str:
        return {
            "MICRO_HYPO": "小细胞低色素倾向",
            "MICRO": "小细胞倾向",
            "MACRO": "大细胞倾向",
            "ANEMIA": "血红蛋白偏低",
            "POLYCYTHEMIA_SUSPECT": "红细胞增多倾向",
            "THROMBOCYTOPENIA": "血小板偏低",
            "THROMBOCYTOSIS": "血小板偏高",
            "LEUKOCYTOSIS": "白细胞升高倾向",
            "LEUKOPENIA": "白细胞偏低",
            "MULTI_ABNORMAL": "多项异常",
            "NORMAL": "未见异常",
            "UNCLASSIFIED": "其他异常组合",
        }[self.value]


# 表顺序即优先级：同一样本命中多条时，取最先命中者作为主模式（5.1 的隐含约定）
PATTERN_ORDER: tuple[Pattern, ...] = (
    Pattern.MICRO_HYPO,
    Pattern.MICRO,
    Pattern.MACRO,
    Pattern.ANEMIA,
    Pattern.POLYCYTHEMIA_SUSPECT,
    Pattern.THROMBOCYTOPENIA,
    Pattern.THROMBOCYTOSIS,
    Pattern.LEUKOCYTOSIS,
    Pattern.LEUKOPENIA,
)


@dataclass(frozen=True)
class MetricFlag:
    metric: str
    value: float | None
    status: MetricStatus
    low: float | None = None
    high: float | None = None
    unit: str = ""
    name_cn: str = ""
    deviation_pct: float = 0.0
    pos: float | None = None
    ratio_to_bound: float | None = None
    reason: str | None = None  # gender_missing / no_interval / missing_value
    ri_source: str = "default"  # default / female / unified（8.1 的 ri_source）

    @property
    def abnormal(self) -> bool:
        return self.status in (MetricStatus.HIGH, MetricStatus.LOW)

    def to_payload(self) -> dict:
        return {
            "metric": self.metric,
            "name_cn": self.name_cn,
            "value": None if self.value is None else round(self.value, 2),
            "unit": self.unit,
            "low": self.low,
            "high": self.high,
            "status": self.status.value,
            "symbol": self.status.symbol,
            "text": self.status.text_cn,
            "color_token": self.status.color_token,
            "deviation_pct": self.deviation_pct,
            "pos": self.pos,
            "ratio_to_bound": self.ratio_to_bound,
            "missing": self.value is None,
            "reason": self.reason,
            "ri_source": self.ri_source,
        }


@dataclass
class SampleVerdict:
    sample_index: int
    gender: str | None
    age: float | None
    flags: dict[str, MetricFlag] = field(default_factory=dict)
    patterns: list[Pattern] = field(default_factory=list)
    severity: float = 0.0

    @property
    def pattern(self) -> Pattern:
        return self.patterns[0] if self.patterns else Pattern.NORMAL

    @property
    def abnormal_metrics(self) -> tuple[str, ...]:
        return tuple(m for m, f in self.flags.items() if f.abnormal)

    @property
    def n_abnormal(self) -> int:
        return len(self.abnormal_metrics)

    @property
    def na_metrics(self) -> tuple[str, ...]:
        return tuple(m for m, f in self.flags.items() if f.status is MetricStatus.NA)

    @property
    def gender_missing(self) -> bool:
        return self.gender not in ("male", "female")

    def to_payload(self) -> dict:
        return {
            "sample_index": self.sample_index,
            "gender": self.gender,
            "age": self.age,
            "pattern": self.pattern.value,
            "pattern_text": self.pattern.text_cn,
            "patterns": [p.value for p in self.patterns],
            "severity": round(self.severity, 2),
            "n_abnormal": self.n_abnormal,
            "abnormal_metrics": list(self.abnormal_metrics),
            "na_metrics": list(self.na_metrics),
            "items": [f.to_payload() for f in self.flags.values()],
        }


def judge_metric(
    metric: str,
    value: float | None,
    gender: str | None,
    ranges: ReferenceRanges,
    *,
    unified: bool = False,
) -> MetricFlag:
    """单指标判定。``unified=True`` 时，缺性别的性别依赖指标改用统一区间（FR-16）。"""
    interval, reason = ranges.resolve(metric, gender, unified=unified)
    source = ranges.source_of(metric, gender, unified=unified)
    if interval is None:
        return MetricFlag(
            metric=metric, value=value, status=MetricStatus.NA, reason=reason, ri_source=source
        )
    if value is None:
        return MetricFlag(
            metric=metric,
            value=None,
            status=MetricStatus.NA,
            low=interval.low,
            high=interval.high,
            unit=interval.unit,
            name_cn=interval.name_cn,
            reason="missing_value",
            ri_source=source,
        )
    return MetricFlag(
        metric=metric,
        value=value,
        status=interval.judge(value),
        low=interval.low,
        high=interval.high,
        unit=interval.unit,
        name_cn=interval.name_cn,
        deviation_pct=interval.deviation_pct(value),
        pos=interval.pos(value),
        ratio_to_bound=interval.ratio_to_bound(value),
        ri_source=source,
    )


def detect_patterns(flags: dict[str, MetricFlag]) -> list[Pattern]:
    """BR-07 + 5.1：按受影响指标集合映射模式，返回命中的全部模式（有序）。"""
    status = {m: f.status for m, f in flags.items()}

    def is_(metric: str, want: MetricStatus) -> bool:
        return status.get(metric) is want

    abnormal = [m for m, f in flags.items() if f.abnormal]
    hits: list[Pattern] = []

    if is_("mcv", MetricStatus.LOW) and is_("mch", MetricStatus.LOW) and is_("mchc", MetricStatus.LOW):
        hits.append(Pattern.MICRO_HYPO)
    if is_("mcv", MetricStatus.LOW) and (
        is_("mch", MetricStatus.NORMAL) or is_("mchc", MetricStatus.NORMAL)
    ):
        hits.append(Pattern.MICRO)
    if is_("mcv", MetricStatus.HIGH):
        hits.append(Pattern.MACRO)
    if is_("hgb", MetricStatus.LOW):
        hits.append(Pattern.ANEMIA)
    if is_("hgb", MetricStatus.HIGH) and is_("rbc", MetricStatus.HIGH):
        hits.append(Pattern.POLYCYTHEMIA_SUSPECT)
    if is_("plt", MetricStatus.LOW):
        hits.append(Pattern.THROMBOCYTOPENIA)
    if is_("plt", MetricStatus.HIGH):
        hits.append(Pattern.THROMBOCYTOSIS)
    if is_("wbc", MetricStatus.HIGH) and is_("neut_pct", MetricStatus.HIGH):
        hits.append(Pattern.LEUKOCYTOSIS)
    if is_("wbc", MetricStatus.LOW):
        hits.append(Pattern.LEUKOPENIA)

    if not abnormal:
        return [Pattern.NORMAL]
    if hits:
        return hits
    if len(abnormal) >= 3:
        return [Pattern.MULTI_ABNORMAL]
    # 1–2 项异常但匹配不上任何模式：不硬塞 MULTI_ABNORMAL（那是"≥3 项"的语义），
    # 落到 UNCLASSIFIED（待补入 5.1 表）
    return [Pattern.UNCLASSIFIED]


def severity_of(flags: dict[str, MetricFlag]) -> float:
    """BR-08：``max_i(|x − 最近边界| / 区间宽度 × 100%)``，只统计越界指标。"""
    values = [f.deviation_pct for f in flags.values() if f.abnormal]
    return max(values) if values else 0.0


def judge_sample(
    values: dict[str, float | None],
    *,
    sample_index: int,
    gender: str | None,
    age: float | None,
    ranges: ReferenceRanges,
    metrics: tuple[str, ...] | None = None,
    unified: bool = False,
) -> SampleVerdict:
    wanted = metrics or tuple(values)
    flags: dict[str, MetricFlag] = {}
    for metric in wanted:
        if metric not in values and metric not in ranges.default:
            continue
        flags[metric] = judge_metric(metric, values.get(metric), gender, ranges, unified=unified)
    verdict = SampleVerdict(
        sample_index=sample_index,
        gender=gender,
        age=age,
        flags=flags,
        patterns=detect_patterns(flags),
        severity=severity_of(flags),
    )
    return verdict


def flag_frame(
    frame: pd.DataFrame,
    ranges: ReferenceRanges,
    *,
    metrics: tuple[str, ...] | None = None,
    unified: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """对整个清洗后宽表做判定。

    返回 ``(长表, 样本级汇总)``：长表一行一个"样本×指标"，供导出与体检单；
    汇总表一行一个样本，含模式、严重度、异常指标数。

    ``unified=True`` 仅用于"数据集无性别、用户显式声明按统一区间判定"的场景（FR-16），
    受影响的指标会在长表 ``ri_source`` 列标成 ``unified``。
    """
    # 注意：不能用 `ranges.interval(m)` 判可用性——它对性别依赖指标在没有 gender 时
    # 返回 None（BR-17），会把 hgb/rbc/hct 整列漏掉。这里只问"配置里有没有这个指标"。
    wanted = metrics or tuple(m for m in frame.columns if m in ranges.default)
    # 清洗后一行不剩（例如所有指标列装的都是"正常/阴性"这类文本）时，逐行实现会返回
    # 一个**没有列名**的空 DataFrame，下游 metric_overview 的 long["metric"] 直接抛
    # KeyError，最终变成 500。用户该看到的是"这份数据没通过质量校验"，不是"服务器错误"，
    # 所以空表也必须带正规列名。
    if frame.empty:
        return _empty_long(), _empty_summary()
    if len(frame) >= BULK_FLAG_MIN_ROWS:
        return _flag_frame_bulk(frame, ranges, wanted, unified)
    return _flag_frame_rows(frame, ranges, wanted, unified)


LONG_COLUMNS = (
    "sample_index",
    "gender",
    "age",
    "metric",
    "value",
    "low",
    "high",
    "unit",
    "status",
    "deviation_pct",
    "pos",
    "reason",
    "ri_source",
)

SUMMARY_COLUMNS = (
    "sample_index",
    "gender",
    "age",
    "pattern",
    "patterns",
    "severity",
    "n_abnormal",
    "abnormal_metrics",
    "na_metrics",
    "gender_missing",
    "ri_unified",
)


def _empty_long() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in LONG_COLUMNS})


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in SUMMARY_COLUMNS})


BULK_FLAG_MIN_ROWS = 2000
"""超过这个行数走向量化判定。

逐行 ``iterrows()`` + 每格一个 ``MetricFlag`` 数据类，在 9.6 万行 × 15 指标上是 144 万个
对象，实测 39 s（DS-02）；向量化后同一份数据 ~1 s。阈值取 2000 是为了让"演示级"小数据
仍走逐行实现——它的可读性更好，也更方便调试。
"""


def _flag_frame_rows(
    frame: pd.DataFrame,
    ranges: ReferenceRanges,
    wanted: tuple[str, ...],
    unified: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    long_rows: list[dict] = []
    summary_rows: list[dict] = []

    for position, (_raw_index, row) in enumerate(frame.iterrows()):
        index = int(row["sample_index"]) if "sample_index" in frame.columns else position
        gender = row.get("gender") if "gender" in frame.columns else None
        age = row.get("age") if "age" in frame.columns else None
        values = {m: _as_float(row.get(m)) for m in wanted}
        verdict = judge_sample(
            values,
            sample_index=index,
            gender=gender,
            age=age,
            ranges=ranges,
            metrics=wanted,
            unified=unified,
        )
        for flag in verdict.flags.values():
            long_rows.append(
                {
                    "sample_index": index,
                    "gender": gender,
                    "age": age,
                    "metric": flag.metric,
                    "value": flag.value,
                    "low": flag.low,
                    "high": flag.high,
                    "unit": flag.unit,
                    "status": flag.status.value,
                    "deviation_pct": flag.deviation_pct,
                    "pos": flag.pos,
                    "reason": flag.reason,
                    "ri_source": flag.ri_source,
                }
            )
        summary_rows.append(
            {
                "sample_index": index,
                "gender": gender,
                "age": age,
                "pattern": verdict.pattern.value,
                "patterns": "|".join(p.value for p in verdict.patterns),
                "severity": round(verdict.severity, 2),
                "n_abnormal": verdict.n_abnormal,
                "abnormal_metrics": "|".join(verdict.abnormal_metrics),
                "na_metrics": "|".join(verdict.na_metrics),
                "gender_missing": verdict.gender_missing,
                "ri_unified": any(f.ri_source == "unified" for f in verdict.flags.values()),
            }
        )

    return pd.DataFrame(long_rows), pd.DataFrame(summary_rows)


def _as_float(value: object) -> float | None:
    if value is None or value is pd.NA:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def anomaly_summary(long: pd.DataFrame, summary: pd.DataFrame) -> dict:
    """FR-17 / DQ-06：异常率、模式分布、严重度 Top N 的原料。"""
    total = len(summary)
    abnormal_samples = int((summary["n_abnormal"] > 0).sum()) if total else 0
    pattern_counts = summary["pattern"].value_counts().to_dict() if total else {}
    unified = 0
    if total and "ri_unified" in summary.columns:
        unified = int(summary["ri_unified"].fillna(False).astype(bool).sum())
    return {
        "samples": total,
        "abnormal_samples": abnormal_samples,
        "anomaly_rate": round(abnormal_samples / total, 4) if total else 0.0,
        "abnormal_items": int((long["status"].isin(["HIGH", "LOW"])).sum()) if len(long) else 0,
        "pattern_counts": {str(k): int(v) for k, v in pattern_counts.items()},
        "na_samples": int(summary["na_metrics"].str.len().gt(0).sum()) if total else 0,
        "gender_missing_samples": int(summary["gender_missing"].sum()) if total else 0,
        "unified_samples": unified,
    }


def rejudge_metrics(
    frame: pd.DataFrame,
    long: pd.DataFrame,
    ranges: ReferenceRanges,
    metrics: tuple[str, ...],
    *,
    unified: bool = False,
) -> pd.DataFrame:
    """只重判指定指标，其余行原样保留（FR-37 临时试算用）。

    为什么不整表重判：10 万行整表重判约 5 s，而用户拖动一条参考线时期望的是**即时**
    反应（NFR-P-12 要求 ≤800 ms）。只重算被拖的那一个指标，代价是每指标 ~0.1 s。
    合并后的行序会变（重算的行被排到末尾），但图表与体检单都按 ``metric`` 过滤，
    不依赖行序；``sample_index`` 一个都没动。
    """
    targets = tuple(m for m in metrics if m in ranges.default and m in frame.columns)
    if not targets:
        return long
    keep = long.loc[~long["metric"].isin(targets)]
    rebuilt, _ = flag_frame(frame, ranges, metrics=targets, unified=unified)
    return pd.concat([keep, rebuilt], ignore_index=True)


def reference_snapshot_of(interval: Interval | None) -> dict | None:
    if interval is None:
        return None
    return {"low": interval.low, "high": interval.high, "unit": interval.unit}


def _flag_frame_bulk(
    frame: pd.DataFrame,
    ranges: ReferenceRanges,
    wanted: tuple[str, ...],
    unified: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """向量化判定：逐指标一次性算完，语义与 ``_flag_frame_rows`` 完全一致。

    为什么值得单独写一份：9.6 万行 × 15 指标 = 144 万个 ``MetricFlag`` 对象，
    逐行构造实测 39 s；这里改成 numpy 掩码后约 1 s。两份实现互为**参照实现**，
    ``tests/test_bulk_flag.py`` 会在同一份数据上比对全部输出列。
    """
    n = len(frame)
    if "sample_index" in frame.columns:
        index = frame["sample_index"].to_numpy(dtype="int64")
    else:
        index = np.arange(n, dtype="int64")
    if "gender" in frame.columns:
        gender = np.array(
            [g if isinstance(g, str) else None for g in frame["gender"].to_numpy(dtype=object)],
            dtype=object,
        )
    else:
        gender = np.full(n, None, dtype=object)
    age = (
        pd.to_numeric(frame["age"], errors="coerce").to_numpy(dtype="float64")
        if "age" in frame.columns
        else np.full(n, np.nan)
    )
    known = np.isin(gender, ("male", "female"))
    is_female = np.array([g == "female" for g in gender], dtype=bool)

    blocks: list[pd.DataFrame] = []
    deviation_columns: list[np.ndarray] = []
    status_of: dict[str, np.ndarray] = {}
    unified_any = np.zeros(n, dtype=bool)

    for metric in wanted:
        base = ranges.default.get(metric)
        if base is None:
            continue
        # 依赖性别 = 没有性别时 resolve 拿不到区间
        dependent = ranges.resolve(metric, None, unified=False)[0] is None
        female_interval = ranges.female_overrides.get(metric) if dependent else None

        low = np.full(n, base.low, dtype="float64")
        high = np.full(n, base.high, dtype="float64")
        source = np.full(n, "default", dtype=object)
        usable = np.ones(n, dtype=bool)
        if female_interval is not None:
            low = np.where(is_female, female_interval.low, low)
            high = np.where(is_female, female_interval.high, high)
            source = np.where(is_female, "female", source)
        if dependent:
            missing = ~known
            if unified:
                source = np.where(missing, "unified", source)
            else:
                usable = known
        if not usable.all():
            # 无区间可用的行，low/high 必须是空：给个默认下限会让人以为"按男区间判过"
            low = np.where(usable, low, np.nan)
            high = np.where(usable, high, np.nan)

        values = pd.to_numeric(frame[metric], errors="coerce").to_numpy(dtype="float64")
        blank = np.isnan(values)
        status = np.full(n, MetricStatus.NORMAL.value, dtype=object)
        below = np.where(usable, values < low, False)
        above = np.where(usable, values > high, False)
        status[below] = MetricStatus.LOW.value
        status[above] = MetricStatus.HIGH.value
        na = ~usable | blank
        status[na] = MetricStatus.NA.value

        reason = np.full(n, None, dtype=object)
        reason[blank & usable] = "missing_value"
        reason[~usable] = "gender_missing"

        width = high - low
        safe = np.where(width > 0, width, 1.0)
        distance = np.where(values < low, low - values, np.where(values > high, values - high, 0.0))
        deviation = np.where(na, 0.0, np.round(distance / safe * 100, 2))
        # NA 行的 pos 是 None 而不是 0：0 会被前端画成"贴着下界"，这是 FR-31 明令禁止的
        # 那种"看起来很像真的"的假数据。逐行实现里 MetricFlag.pos 默认就是 None。
        position = np.where(na, None, np.round((values - low) / safe, 4)).astype(object)
        abnormal = np.isin(status, (MetricStatus.LOW.value, MetricStatus.HIGH.value))
        deviation_columns.append(np.where(abnormal, deviation, 0.0))
        status_of[metric] = status
        unified_any |= source == "unified"

        blocks.append(
            pd.DataFrame(
                {
                    "sample_index": index,
                    "gender": gender,
                    "age": age,
                    "metric": metric,
                    "value": values,
                    "low": low,
                    "high": high,
                    "unit": np.where(usable, base.unit, ""),
                    "status": status,
                    "deviation_pct": deviation,
                    "pos": position,
                    "reason": reason,
                    "ri_source": source,
                }
            )
        )

    if blocks:
        long = pd.concat(blocks, ignore_index=True)
        status_matrix = np.column_stack([status_of[m] for m in wanted if m in status_of])
        deviation_matrix = np.column_stack(deviation_columns)
    else:
        long = pd.DataFrame(
            columns=[
                "sample_index",
                "gender",
                "age",
                "metric",
                "value",
                "low",
                "high",
                "unit",
                "status",
                "deviation_pct",
                "pos",
                "reason",
                "ri_source",
            ]
        )
        status_matrix = np.zeros((n, 0), dtype=object)
        deviation_matrix = np.zeros((n, 0), dtype=float)

    used = [m for m in wanted if m in status_of]
    abnormal_matrix = np.isin(status_matrix, (MetricStatus.LOW.value, MetricStatus.HIGH.value))
    n_abnormal = abnormal_matrix.sum(axis=1) if used else np.zeros(n, dtype="int64")
    severity = np.round(deviation_matrix.max(axis=1), 2) if used else np.zeros(n)

    def is_(metric: str, state: MetricStatus) -> np.ndarray:
        if metric not in status_of:
            return np.zeros(n, dtype=bool)
        return status_of[metric] == state.value

    pattern_masks: list[tuple[str, np.ndarray]] = [
        (
            Pattern.MICRO_HYPO.value,
            is_("mcv", MetricStatus.LOW) & is_("mch", MetricStatus.LOW) & is_("mchc", MetricStatus.LOW),
        ),
        (
            Pattern.MICRO.value,
            is_("mcv", MetricStatus.LOW)
            & (is_("mch", MetricStatus.NORMAL) | is_("mchc", MetricStatus.NORMAL)),
        ),
        (Pattern.MACRO.value, is_("mcv", MetricStatus.HIGH)),
        (Pattern.ANEMIA.value, is_("hgb", MetricStatus.LOW)),
        (
            Pattern.POLYCYTHEMIA_SUSPECT.value,
            is_("hgb", MetricStatus.HIGH) & is_("rbc", MetricStatus.HIGH),
        ),
        (Pattern.THROMBOCYTOPENIA.value, is_("plt", MetricStatus.LOW)),
        (Pattern.THROMBOCYTOSIS.value, is_("plt", MetricStatus.HIGH)),
        (Pattern.LEUKOCYTOSIS.value, is_("wbc", MetricStatus.HIGH) & is_("neut_pct", MetricStatus.HIGH)),
        (Pattern.LEUKOPENIA.value, is_("wbc", MetricStatus.LOW)),
    ]

    joined = np.full(n, "", dtype=object)
    first_hit = np.full(n, "", dtype=object)
    for name, mask in pattern_masks:
        joined = np.where(mask, np.where(joined == "", name, joined + "|" + name), joined)
        first_hit = np.where(mask & (first_hit == ""), name, first_hit)

    abnormal_any = n_abnormal > 0
    fallback = np.where(
        n_abnormal >= 3, Pattern.MULTI_ABNORMAL.value, Pattern.UNCLASSIFIED.value
    )
    primary = np.where(abnormal_any, np.where(first_hit == "", fallback, first_hit), Pattern.NORMAL.value)
    patterns = np.where(abnormal_any, np.where(first_hit == "", fallback, joined), Pattern.NORMAL.value)

    abnormal_metrics = [
        "|".join(metric for metric, flag in zip(used, row, strict=False) if flag)
        for row in abnormal_matrix
    ]
    na_metrics = [
        "|".join(metric for metric, flag in zip(used, row, strict=False) if flag)
        for row in status_matrix == MetricStatus.NA.value
    ]

    summary = pd.DataFrame(
        {
            "sample_index": index,
            "gender": gender,
            "age": age,
            "pattern": primary,
            "patterns": patterns,
            "severity": severity,
            "n_abnormal": n_abnormal,
            "abnormal_metrics": abnormal_metrics,
            "na_metrics": na_metrics,
            "gender_missing": ~known,
            "ri_unified": unified_any,
        }
    )
    return long, summary
