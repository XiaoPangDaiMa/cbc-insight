"""向量化判定与逐行判定必须给出**完全相同**的结果（B1 性能优化引入）。

``rules._flag_frame_rows`` 是可读的参照实现，``rules._flag_frame_bulk`` 是 3.9 万倍快的
生产实现。两份实现只要有一天漂移，"同一行数据在 100 行文件和 10 万行文件里判定不同"
这种 bug 就会悄悄发生——所以这里逐列比对。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from app.pipeline.rules import _flag_frame_bulk, _flag_frame_rows

LONG_COLUMNS = [
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
SUMMARY_COLUMNS = [
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
]


def _frame() -> pd.DataFrame:
    """30 行，覆盖：男女/缺性别、正常/偏低/偏高、缺失值、非性别相关指标异常。"""
    rows = []
    genders = ["male", "female", None]
    for i in range(30):
        gender = genders[i % 3]
        base = {
            "sample_index": i,
            "gender": gender,
            "age": 20.0 + (i % 50),
            "hgb": [142.0, 120.0, 100.0, 160.0, np.nan][i % 5],
            "rbc": [4.9, 4.2, 3.4, 5.9, 4.6][i % 5],
            "wbc": [6.0, 9.9, 3.0, 12.0, 7.0][i % 5],
            "plt": [230.0, 400.0, 100.0, 310.0, np.nan][i % 5],
            "hct": [44.0, 38.0, 30.0, 52.0, 42.0][i % 5],
            "mcv": [90.0, 80.0, 70.0, 105.0, 88.0][i % 5],
            "mch": [30.0, 26.0, 22.0, 36.0, 29.0][i % 5],
            "mchc": [330.0, 340.0, 300.0, 360.0, 325.0][i % 5],
            "neut_pct": [60.0, 70.0, 50.0, 80.0, 55.0][i % 5],
        }
        rows.append(base)
    return pd.DataFrame(rows)


def _normalize(frame: pd.DataFrame, columns: list[str], keys: list[str]) -> pd.DataFrame:
    frame = frame.loc[:, columns].sort_values(keys).reset_index(drop=True)
    for column in frame.columns:
        if frame[column].dtype == object or frame[column].isna().any():
            frame[column] = frame[column].astype(object).where(frame[column].notna(), None)
    return frame


@pytest.mark.parametrize("unified", [False, True])
def test_bulk_matches_rows(ranges, unified):
    frame = _frame()
    wanted = tuple(c for c in frame.columns if c in ranges.default)
    long_rows, summary_rows = _flag_frame_rows(frame, ranges, wanted, unified)
    long_bulk, summary_bulk = _flag_frame_bulk(frame, ranges, wanted, unified)

    assert list(long_bulk.columns) == LONG_COLUMNS
    assert list(summary_bulk.columns) == SUMMARY_COLUMNS

    keys = ["sample_index", "metric"]
    assert_frame_equal(
        _normalize(long_rows, LONG_COLUMNS, keys),
        _normalize(long_bulk, LONG_COLUMNS, keys),
        check_dtype=False,
    )
    assert_frame_equal(
        _normalize(summary_rows, SUMMARY_COLUMNS, ["sample_index"]),
        _normalize(summary_bulk, SUMMARY_COLUMNS, ["sample_index"]),
        check_dtype=False,
    )


def test_bulk_gender_missing_is_na_without_unified(ranges):
    frame = _frame()
    wanted = ("hgb", "wbc")
    long, _ = _flag_frame_bulk(frame, ranges, wanted, unified=False)
    missing = long[(long["sample_index"] % 3 == 2) & (long["metric"] == "hgb")]
    assert set(missing["status"]) == {"NA"}
    assert set(missing["reason"]) == {"gender_missing"}


def test_bulk_unified_marks_source(ranges):
    frame = _frame()
    long, summary = _flag_frame_bulk(frame, ranges, ("hgb",), unified=True)
    missing = long[long["sample_index"] % 3 == 2]
    assert set(missing["ri_source"]) == {"unified"}
    assert summary["ri_unified"].sum() == 10
