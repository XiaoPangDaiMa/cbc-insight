"""BR-01 区间边界语义：闭区间，边界值属于正常。"""

from __future__ import annotations

from app.pipeline.reference import MetricStatus


def test_hgb_boundary_is_normal_for_male(ranges):
    # T-05：男性 hgb = 130（下限）判 NORMAL
    interval = ranges.interval("hgb", "male")
    assert interval.judge(130) is MetricStatus.NORMAL
    assert interval.judge(175) is MetricStatus.NORMAL


def test_just_outside_boundary_is_flagged(ranges):
    interval = ranges.interval("hgb", "male")
    assert interval.judge(129.9) is MetricStatus.LOW
    assert interval.judge(175.1) is MetricStatus.HIGH


def test_female_override_used(ranges):
    # T-06：女性 hgb = 120 判 NORMAL（女性下限 115），同一数值男性判 LOW
    assert ranges.interval("hgb", "female").judge(120) is MetricStatus.NORMAL
    assert ranges.interval("hgb", "male").judge(120) is MetricStatus.LOW


def test_single_interval_metric_ignores_gender(ranges):
    interval = ranges.interval("mcv", "female")
    assert interval.judge(82) is MetricStatus.NORMAL
    assert interval.judge(100) is MetricStatus.NORMAL
    assert interval.judge(101) is MetricStatus.HIGH


def test_boundary_value_in_fixture_is_normal(pipeline, clean_csv):
    result = pipeline(clean_csv)
    row = result.long[result.long["sample_index"] == 2]
    mcv = row[row["metric"] == "mcv"].iloc[0]
    assert mcv["value"] == 99
    assert mcv["status"] == "NORMAL"
