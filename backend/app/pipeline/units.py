"""单位与量纲归一（SRS 3.4、BR-02）。

3.4 的原则是"宁可报警不猜测"：中位数落在两个量级之间时，必须阻塞并请用户确认，
不允许静默换算。因此本模块只负责"判定"，是否阻塞由调用方决定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

# (下界含, 上界不含, 判定出的原单位, 归一系数) —— 归一目标见 NORMALIZED_UNITS
# 模糊带 = 下界为 None 的那一档，落在带内即"无法判定"，不换算。
SCALE_RULES: dict[str, tuple[tuple[float | None, float | None, str, float], ...]] = {
    "hgb": ((0, 30, "g/dL", 10.0), (30, 100, "", 1.0), (100, None, "g/L", 1.0)),
    "mchc": ((0, 100, "g/dL", 10.0), (100, 300, "", 1.0), (300, None, "g/L", 1.0)),
    "wbc": ((0, 20, "10^9/L", 1.0), (20, 100, "", 1.0), (100, None, "个/µL", 0.001)),
    "rbc": ((0, 8, "10^12/L", 1.0), (8, 50, "", 1.0), (50, None, "万/µL", 0.01)),
    # 血小板：3.4 原文写"两种写法数值等价，只统一标签"，实测 DS-01 的 PLT 是
    # 310000（个/µL），与 310（×10⁹/L）差 1000 倍，并非等价。这里补上换算规则，
    # 否则整列会被判成"偏高"（B1 真实数据体检发现，已回写 SRS 3.4）。
    "plt": ((0, 2000, "10^9/L", 1.0), (2000, 10000, "", 1.0), (10000, None, "个/µL", 0.001)),
    # 五分类绝对值（v1.9，check_only）：与 WBC 同一量级，按同样的三档判。
    # 它们不参与判定，但仍要归一——否则 WBC 换算过、绝对值没换算，BR-23 的
    # 交叉校验会把"单位没统一"报成"两列数据打架"。
    **dict.fromkeys(
        ("neut_abs", "lymph_abs", "mono_abs", "eo_abs", "baso_abs"),
        ((0, 20, "10^9/L", 1.0), (20, 100, "", 1.0), (100, None, "个/µL", 0.001)),
    ),
}

NORMALIZED_UNITS: dict[str, str] = {
    "hgb": "g/L",
    "mchc": "g/L",
    "wbc": "10^9/L",
    "rbc": "10^12/L",
    "plt": "10^9/L",
    # 五分类绝对值与 WBC 同单位
    **dict.fromkeys(("neut_abs", "lymph_abs", "mono_abs", "eo_abs", "baso_abs"), "10^9/L"),
}

# 只统一标签、不做数值换算的指标（目前为空：plt 已补上换算规则）
LABEL_ONLY: set[str] = set()


@dataclass(frozen=True)
class UnitDecision:
    metric: str
    detected_unit: str
    target_unit: str
    factor: float
    ambiguous: bool = False
    candidates: tuple[str, ...] = ()
    median: float | None = None

    @property
    def converted(self) -> bool:
        return self.factor != 1.0

    def log_line(self) -> str:
        if not self.converted:
            return ""
        return f"{self.metric} 原单位 {self.detected_unit} → {self.target_unit}（×{self.factor:g}）"

    @property
    def note(self) -> str:
        return f"{self.metric} 原单位 {self.detected_unit} 已按 ×{self.factor:g} 归一" if self.converted else ""


def detect_unit(metric: str, series: pd.Series, *, forced_unit: str | None = None) -> UnitDecision:
    """按列中位数判定单位（3.4 判定规则列）。"""
    target = NORMALIZED_UNITS.get(metric, "")
    numeric = pd.to_numeric(series, errors="coerce")
    median = float(numeric.median()) if numeric.notna().any() else None

    if forced_unit:
        factor = _factor_for(metric, forced_unit)
        return UnitDecision(metric, forced_unit, target or forced_unit, factor, median=median)

    if median is None or not math.isfinite(median) or metric in LABEL_ONLY:
        return UnitDecision(metric, target or metric, target or metric, 1.0, median=median)

    rules = SCALE_RULES.get(metric)
    if not rules:
        return UnitDecision(metric, target or metric, target or metric, 1.0, median=median)

    for low, high, unit, factor in rules:
        if low is not None and median < low:
            continue
        if high is not None and median >= high:
            continue
        if not unit:  # 模糊带
            below = rules[rules.index((low, high, unit, factor)) - 1]
            above = rules[rules.index((low, high, unit, factor)) + 1]
            return UnitDecision(
                metric=metric,
                detected_unit="?",
                target_unit=target or metric,
                factor=1.0,
                ambiguous=True,
                candidates=(below[2], above[2]),
                median=median,
            )
        return UnitDecision(metric, unit, target or unit, factor, median=median)

    return UnitDecision(metric, target or metric, target or metric, 1.0, median=median)


def _factor_for(metric: str, unit: str) -> float:
    for _low, _high, rule_unit, factor in SCALE_RULES.get(metric, ()):
        if rule_unit and rule_unit == unit:
            return factor
    if unit == NORMALIZED_UNITS.get(metric):
        return 1.0
    raise KeyError(f"未知单位：{metric}={unit}")


def detect_all(
    frame: pd.DataFrame, metrics: tuple[str, ...], *, forced: dict[str, str] | None = None
) -> list[UnitDecision]:
    forced = forced or {}
    decisions: list[UnitDecision] = []
    for metric in metrics:
        if metric not in frame.columns:
            continue
        decisions.append(detect_unit(metric, frame[metric], forced_unit=forced.get(metric)))
    return decisions


def apply_decisions(
    frame: pd.DataFrame, decisions: list[UnitDecision]
) -> tuple[pd.DataFrame, list[str]]:
    """按 3.4 归一化动作换算，返回 (新表, 日志行)。模糊单位不换算、不修改数据。"""
    out = frame.copy()
    log: list[str] = []
    for decision in decisions:
        if not decision.converted or decision.ambiguous:
            continue
        out[decision.metric] = pd.to_numeric(out[decision.metric], errors="coerce") * decision.factor
        line = decision.log_line()
        if line:
            log.append(line)
    return out, log
