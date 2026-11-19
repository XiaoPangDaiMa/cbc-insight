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


def judge_metric(metric: str, value: float | None, gender: str | None, ranges: ReferenceRanges) -> MetricFlag:
    interval, reason = ranges.resolve(metric, gender)
    if interval is None:
        return MetricFlag(metric=metric, value=value, status=MetricStatus.NA, reason=reason)
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
) -> SampleVerdict:
    wanted = metrics or tuple(values)
    flags: dict[str, MetricFlag] = {}
    for metric in wanted:
        if metric not in values and metric not in ranges.default:
            continue
        flags[metric] = judge_metric(metric, values.get(metric), gender, ranges)
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
    frame: pd.DataFrame, ranges: ReferenceRanges, *, metrics: tuple[str, ...] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """对整个清洗后宽表做判定。

    返回 ``(长表, 样本级汇总)``：长表一行一个"样本×指标"，供导出与体检单；
    汇总表一行一个样本，含模式、严重度、异常指标数。
    """
    # 注意：不能用 `ranges.interval(m)` 判可用性——它对性别依赖指标在没有 gender 时
    # 返回 None（BR-17），会把 hgb/rbc/hct 整列漏掉。这里只问"配置里有没有这个指标"。
    wanted = metrics or tuple(m for m in frame.columns if m in ranges.default)
    long_rows: list[dict] = []
    summary_rows: list[dict] = []

    for position, (_raw_index, row) in enumerate(frame.iterrows()):
        index = int(row["sample_index"]) if "sample_index" in frame.columns else position
        gender = row.get("gender") if "gender" in frame.columns else None
        age = row.get("age") if "age" in frame.columns else None
        values = {m: _as_float(row.get(m)) for m in wanted}
        verdict = judge_sample(
            values, sample_index=index, gender=gender, age=age, ranges=ranges, metrics=wanted
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
    return {
        "samples": total,
        "abnormal_samples": abnormal_samples,
        "anomaly_rate": round(abnormal_samples / total, 4) if total else 0.0,
        "abnormal_items": int((long["status"].isin(["HIGH", "LOW"])).sum()) if len(long) else 0,
        "pattern_counts": {str(k): int(v) for k, v in pattern_counts.items()},
        "na_samples": int(summary["na_metrics"].str.len().gt(0).sum()) if total else 0,
        "gender_missing_samples": int(summary["gender_missing"].sum()) if total else 0,
    }


def reference_snapshot_of(interval: Interval | None) -> dict | None:
    if interval is None:
        return None
    return {"low": interval.low, "high": interval.high, "unit": interval.unit}
