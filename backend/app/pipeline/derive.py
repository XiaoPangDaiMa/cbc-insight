"""S5 派生（SRS 9 章 S5、BR-09、1.4「样本序号」）。

派生两样东西：
* ``age_band``：BR-09 的稳定分箱，供分组统计与"分组中位数填充"使用。
* ``sample_index``：清洗后宽表里的稳定行序（0 起）。它是本期定位单条样本的唯一标识，
  图表点位、体检单接口、导出文件三处必须同源（FR-35 硬约束 4）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# BR-09：18–29 / 30–39 / 40–49 / 50–59 / 60+
AGE_BANDS: tuple[tuple[int, int, str], ...] = (
    (18, 29, "18-29"),
    (30, 39, "30-39"),
    (40, 49, "40-49"),
    (50, 59, "50-59"),
    (60, 200, "60+"),
)
MINOR_BAND = "minor"
UNKNOWN_BAND = "Unknown"


def age_band(age: float | int | None) -> str:
    """BR-09。缺失 → ``Unknown``（BR-17：不并入任何年龄段）；<18 → ``minor``。"""
    if age is None:
        return UNKNOWN_BAND
    try:
        value = float(age)
    except (TypeError, ValueError):
        return UNKNOWN_BAND
    if not np.isfinite(value):
        return UNKNOWN_BAND
    if value < 18:
        return MINOR_BAND
    for low, high, label in AGE_BANDS:
        if low <= value <= high:
            return label
    return "60+"


def add_age_band(frame: pd.DataFrame, *, source: str = "age") -> pd.DataFrame:
    out = frame.copy()
    if source in out.columns:
        out["age_band"] = [age_band(v) for v in out[source]]
    else:
        out["age_band"] = UNKNOWN_BAND
    return out


def add_sample_index(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.reset_index(drop=True).copy()
    out["sample_index"] = np.arange(len(out), dtype=int)
    return out


def derive(frame: pd.DataFrame) -> pd.DataFrame:
    """S5 的完整派生步骤。"""
    out = add_age_band(frame)
    out = add_sample_index(out)
    return out
