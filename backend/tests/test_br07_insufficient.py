"""P2-③：能判的指标不足 3 个时，不给模式。

"1 个指标偏高"和"9 个指标里 1 个偏高"是两件事。后者叫单项异常，
前者只说明**这次能判的东西太少**——常见于单位没认对、区间缺项、缺性别。
把它写成"单项异常"会让一份数据看起来有结论。
"""

from __future__ import annotations

import pandas as pd

from app.pipeline.rules import (
    MIN_JUDGED_METRICS,
    Pattern,
    flag_frame,
    judge_sample,
)


def _verdict(ranges, values: dict[str, float | None], *, gender: str | None = "male"):
    return judge_sample(values, sample_index=0, gender=gender, age=30, ranges=ranges)


def test_two_judged_metrics_is_not_a_pattern(ranges) -> None:
    verdict = _verdict(ranges, {"plt": 80.0, "wbc": 6.0})
    assert verdict.patterns == [Pattern.INSUFFICIENT_METRICS]
    # 该样本仍然"有异常"，只是不给模式——异常清单靠 status，不靠 pattern
    assert any(flag.abnormal for flag in verdict.flags.values())


def test_three_judged_metrics_can_be_normal(ranges) -> None:
    verdict = _verdict(ranges, {"plt": 220.0, "wbc": 6.0, "rdw": 13.2})
    assert len(verdict.flags) >= MIN_JUDGED_METRICS
    assert verdict.patterns == [Pattern.NORMAL]


def test_all_na_is_not_normal(ranges) -> None:
    """全 NA 不能落进"未见异常"——那是"没测"与"正常"混为一谈。"""
    verdict = _verdict(ranges, {"hgb": None, "rbc": None, "hct": None}, gender=None)
    assert verdict.patterns == [Pattern.INSUFFICIENT_METRICS]


def test_bulk_path_applies_the_same_rule(ranges) -> None:
    """向量化路径必须与逐行路径同口径（2500 行才会走 bulk）。"""
    rows = 2500
    frame = pd.DataFrame(
        {
            "sample_index": range(rows),
            "plt": [220.0] * rows,
            "wbc": [6.0] * rows,
        }
    )
    long, summary = flag_frame(frame, ranges, metrics=("plt", "wbc"))
    assert set(summary["pattern"]) == {Pattern.INSUFFICIENT_METRICS.value}
    # 指标确实被判过（不是"全 NA 所以不足"）
    assert (long["status"] == "NORMAL").all()


def test_threshold_is_documented_as_three(ranges) -> None:
    assert MIN_JUDGED_METRICS == 3
    assert Pattern.INSUFFICIENT_METRICS.text_cn
