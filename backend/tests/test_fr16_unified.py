"""FR-16 的唯一例外：无性别数据集按统一区间判定（B1 引入，SRS v1.6）。

三条不能被违反的底线，各一组用例：

1. **默认不猜**（BR-17）：没有 gender 时 hgb/rbc/hct 判 NA，原因 ``gender_missing``。
2. **显式才生效**：只有传 ``unified=True`` 才用 default 区间，且结果标 ``ri_source=unified``。
3. **文字不能撒谎**：统一区间的图注必须写"统一区间"，不得写"按性别各自参考区间"。
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.pipeline.captions import caption_box, caption_hist
from app.pipeline.rules import flag_frame
from app.pipeline.units import detect_unit


@pytest.fixture()
def ranges(ranges):  # noqa: PT004 - 复用 conftest 的 ReferenceRanges
    return ranges


def _frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["sample_index"] = range(len(frame))
    return frame


def test_gender_missing_stays_na_by_default(ranges):
    frame = _frame([{"hgb": 120.0, "wbc": 6.0, "plt": 200.0}])
    long, _summary = flag_frame(frame, ranges)
    hgb = long.loc[long["metric"] == "hgb"].iloc[0]
    assert hgb["status"] == "NA"
    assert hgb["reason"] == "gender_missing"
    assert hgb["ri_source"] == "default"
    # 非性别相关指标照常判定
    assert long.loc[long["metric"] == "wbc"].iloc[0]["status"] == "NORMAL"


def test_unified_switch_enables_gender_dependent_metrics(ranges):
    frame = _frame([{"hgb": 120.0, "wbc": 6.0, "plt": 200.0}])
    long, summary = flag_frame(frame, ranges, unified=True)
    hgb = long.loc[long["metric"] == "hgb"].iloc[0]
    assert hgb["status"] == "LOW"  # 统一区间 = default = 男 130–175
    assert hgb["reason"] is None or pd.isna(hgb["reason"])
    assert hgb["ri_source"] == "unified"
    assert int(hgb["low"]) == 130 and int(hgb["high"]) == 175
    assert bool(summary.iloc[0]["ri_unified"]) is True


def test_unified_does_not_override_known_gender(ranges):
    frame = _frame([{"gender": "female", "hgb": 120.0}])
    long, _ = flag_frame(frame, ranges, unified=True)
    hgb = long.loc[long["metric"] == "hgb"].iloc[0]
    assert hgb["status"] == "NORMAL"  # 女性 115–150
    assert hgb["ri_source"] == "female"


def test_unified_caption_says_unified_not_by_gender():
    caption = caption_box(
        metric_cn="血红蛋白",
        unit="g/L",
        groups={"all": {"n": 20, "median": 137.0}},
        unified_bands=(130.0, 175.0),
        decimals=0,
    )
    assert caption.branch == "unified"
    assert "统一区间" in caption.text
    assert "按性别" not in caption.text


def test_unified_hist_caption_says_unified():
    caption = caption_hist(
        metric_cn="血红蛋白",
        unit="g/L",
        n=100,
        median=137.0,
        low=130.0,
        high=175.0,
        pct_normal=0.7,
        decimals=0,
        unified=True,
    )
    assert caption.branch == "unified"
    assert "统一区间" in caption.text
    assert "按性别各自参考区间判定" not in caption.text
    assert "70% 在区间内" in caption.text


def test_platelet_in_per_microliter_is_converted():
    """DS-01 真实数据里的 PLT 是 310000 个/µL，不换算会让整列判"偏高"。"""
    decision = detect_unit("plt", pd.Series([310000, 250000, 180000]))
    assert decision.factor == 0.001
    assert decision.detected_unit == "个/µL"


def test_platelet_in_si_is_untouched():
    decision = detect_unit("plt", pd.Series([310, 250, 180]))
    assert decision.factor == 1.0
