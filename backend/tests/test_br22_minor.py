"""BR-22：18 岁以下不套成人参考区间。

默认区间来自 WS/T 405-2012，适用 18–120 岁。给 12 岁的样本套成人表，会把儿童本就
偏低的血红蛋白判成"偏低"——这不是"宽松一点"的问题，是拿错尺子。儿科区间没有纳入
默认表，所以未成年人一律判 ``NA`` + ``minor_age``，并且不参与异常率。
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.pipeline.derive import add_sample_index
from app.pipeline.rules import anomaly_summary, flag_frame


def _frame(rows: list[dict]) -> pd.DataFrame:
    base = {"wbc": 7.0, "plt": 250.0, "rbc": 4.5, "mcv": 90.0, "mch": 30.0, "mchc": 330.0}
    records = []
    for index, row in enumerate(rows):
        record = {**base, **row}
        record.setdefault("gender", "female")
        records.append({"sample_index": index, **record})
    return add_sample_index(pd.DataFrame(records))


def test_minor_is_not_judged(ranges) -> None:
    frame = _frame([{"age": 12.0, "hgb": 100.0}, {"age": 30.0, "hgb": 100.0}])
    long, summary = flag_frame(frame, ranges)
    hgb = long.loc[long["metric"] == "hgb"].set_index("sample_index")

    # 12 岁：NA，但参考区间照给（界面要能说清"如果按成人表会在哪"）
    assert hgb.loc[0, "status"] == "NA"
    assert hgb.loc[0, "reason"] == "minor_age"
    assert hgb.loc[0, "low"] == 115.0
    assert hgb.loc[0, "high"] == 150.0

    # 30 岁同样 100 g/L：这才是真的偏低
    assert hgb.loc[1, "status"] == "LOW"

    # 未成年人整体不算"异常样本"，也不进异常清单
    assert summary.loc[summary["sample_index"] == 0, "n_abnormal"].iloc[0] == 0
    assert summary.loc[summary["sample_index"] == 1, "n_abnormal"].iloc[0] >= 1


def test_minor_excluded_from_anomaly_rate(ranges) -> None:
    frame = _frame([{"age": 30.0, "hgb": 100.0}] * 4 + [{"age": 10.0, "hgb": 90.0}] * 2)
    long, summary = flag_frame(frame, ranges)
    stats = anomaly_summary(long, summary)

    assert stats["samples"] == 6
    # 4 个成人偏低算异常；2 个孩子不参与，不能因为"看起来更糟"把异常率抬高
    assert stats["abnormal_samples"] == 4
    assert stats["anomaly_rate"] == pytest.approx(4 / 6, abs=1e-3)
    assert stats["na_samples"] == 2


def test_minor_handled_by_bulk_path(ranges, monkeypatch) -> None:
    """向量化实现与逐行实现必须给出同样的结论（2000 行以上走 bulk）。"""
    rows = [{"age": 35.0, "hgb": 140.0} for _ in range(2000)]
    rows[7] = {"age": 9.0, "hgb": 95.0}
    rows[999] = {"age": 17.9, "hgb": 95.0}
    frame = _frame(rows)

    long, _ = flag_frame(frame, ranges)
    minors = long.loc[long["sample_index"].isin([7, 999])]
    assert set(minors["status"]) == {"NA"}
    assert set(minors["reason"]) == {"minor_age"}
    assert int((long.loc[long["metric"] == "hgb", "status"] == "NA").sum()) >= 2
