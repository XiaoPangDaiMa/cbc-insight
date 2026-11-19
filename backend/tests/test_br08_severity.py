"""BR-08 严重度：``max_i(|x − 最近边界| / 区间宽度 × 100%)``，只统计越界指标。"""

from __future__ import annotations

import pytest

from app.pipeline.rules import judge_sample


def _severity(ranges, **values) -> float:
    base = {"hgb": 140.0, "rbc": 4.8, "wbc": 6.0, "plt": 220.0, "hct": 42.0,
            "mcv": 90.0, "mch": 29.0, "mchc": 330.0}
    base.update(values)
    verdict = judge_sample(base, sample_index=0, gender="male", age=30, ranges=ranges)
    return verdict.severity


def test_normal_sample_has_zero_severity(ranges):
    assert _severity(ranges) == 0.0


def test_deviation_is_relative_to_interval_width(ranges):
    # MCV 区间 82–100，宽度 18；(82 − 79) / 18 × 100 = 16.67
    assert _severity(ranges, mcv=79.0) == pytest.approx(16.67, abs=0.01)


def test_hgb_uses_gender_interval_width(ranges):
    # 男性 HGB 130–175，宽度 45；(130 − 100) / 45 × 100 = 66.67
    assert _severity(ranges, hgb=100.0) == pytest.approx(66.67, abs=0.01)


def test_severity_takes_the_max_across_metrics(ranges):
    severity = _severity(ranges, mcv=85.0, hgb=100.0)
    assert severity == pytest.approx(66.67, abs=0.01)


def test_above_range_uses_upper_boundary(ranges):
    # MCV 上界 100，宽度 18；(103 − 100) / 18 × 100 = 16.67
    assert _severity(ranges, mcv=103.0) == pytest.approx(16.67, abs=0.01)


def test_severity_is_monotonic(ranges):
    assert _severity(ranges, mcv=70.0) > _severity(ranges, mcv=80.0)
