"""BR-17 关键字段缺失时不得猜测（T-31）。"""

from __future__ import annotations

from app.pipeline.reference import MetricStatus
from app.pipeline.rules import judge_metric, judge_sample

BASE = {"hgb": 152.0, "rbc": 4.9, "hct": 44.0, "wbc": 6.0, "plt": 220.0,
        "mcv": 90.0, "mch": 29.0, "mchc": 330.0}


def test_gender_dependent_metric_is_na_without_gender(ranges):
    flag = judge_metric("hgb", 152.0, None, ranges)
    assert flag.status is MetricStatus.NA
    assert flag.reason == "gender_missing"


def test_gender_independent_metrics_still_judged(ranges):
    for metric in ("wbc", "plt", "mcv"):
        flag = judge_metric(metric, BASE[metric], None, ranges)
        assert flag.status is MetricStatus.NORMAL, metric


def test_female_152_would_be_high_but_missing_gender_is_not_guessed(ranges):
    """152 在女性区间属偏高、在男性区间属正常——正因为两种结论不同，才不许猜。"""
    assert judge_metric("hgb", 152.0, "female", ranges).status is MetricStatus.HIGH
    assert judge_metric("hgb", 152.0, "male", ranges).status is MetricStatus.NORMAL
    assert judge_metric("hgb", 152.0, None, ranges).status is MetricStatus.NA


def test_sample_summary_exposes_gender_missing(ranges):
    verdict = judge_sample(BASE, sample_index=0, gender=None, age=40, ranges=ranges)
    assert verdict.gender_missing is True
    assert {"hgb", "rbc", "hct"} <= set(verdict.na_metrics)
    payload = verdict.to_payload()
    assert payload["na_metrics"]
    assert all(item["reason"] == "gender_missing" for item in payload["items"] if item["status"] == "NA")


def test_unknown_gender_string_is_treated_as_missing(ranges):
    flag = judge_metric("hgb", 140.0, "unknown", ranges)
    assert flag.status is MetricStatus.NA


def test_na_is_never_counted_as_abnormal(ranges):
    verdict = judge_sample(BASE, sample_index=0, gender=None, age=40, ranges=ranges)
    assert "hgb" not in verdict.abnormal_metrics
    assert verdict.severity == 0.0
