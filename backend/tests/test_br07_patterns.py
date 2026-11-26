"""BR-07 / 5.1 异常模式映射。"""

from __future__ import annotations

from app.pipeline.rules import Pattern, detect_patterns, judge_sample

BASE = {
    "hgb": 140.0,
    "rbc": 4.8,
    "wbc": 6.0,
    "plt": 220.0,
    "hct": 42.0,
    "mcv": 90.0,
    "mch": 29.0,
    "mchc": 330.0,
    "rdw": 13.2,
}


def _patterns(ranges, **overrides) -> list[Pattern]:
    values = {**BASE, **overrides}
    verdict = judge_sample(values, sample_index=0, gender="male", age=30, ranges=ranges)
    return verdict.patterns


def test_normal_sample(ranges):
    assert _patterns(ranges) == [Pattern.NORMAL]


def test_micro_hypo_requires_all_three(ranges):
    assert _patterns(ranges, mcv=75.0, mch=22.0, mchc=280.0)[0] is Pattern.MICRO_HYPO


def test_micro_when_only_mcv_low_and_mchc_normal(ranges):
    patterns = _patterns(ranges, mcv=78.0, mch=26.0, mchc=330.0)
    assert Pattern.MICRO in patterns
    assert Pattern.MICRO_HYPO not in patterns


def test_macro(ranges):
    assert _patterns(ranges, mcv=108.0)[0] is Pattern.MACRO


def test_anemia_is_secondary_to_micro(ranges):
    patterns = _patterns(ranges, hgb=100.0, mcv=75.0, mch=22.0, mchc=280.0, hct=30.0)
    assert Pattern.MICRO_HYPO in patterns
    assert Pattern.ANEMIA in patterns
    assert patterns[0] is Pattern.MICRO_HYPO  # 表顺序即优先级


def test_polycythemia_needs_hgb_and_rbc(ranges):
    assert Pattern.POLYCYTHEMIA_SUSPECT in _patterns(ranges, hgb=185.0, rbc=6.2, hct=55.0)
    assert Pattern.POLYCYTHEMIA_SUSPECT not in _patterns(ranges, hgb=185.0, hct=55.0)


def test_platelet_patterns(ranges):
    assert _patterns(ranges, plt=80.0) == [Pattern.THROMBOCYTOPENIA]
    assert _patterns(ranges, plt=420.0) == [Pattern.THROMBOCYTOSIS]


def test_leukocytosis_needs_wbc_and_neut(ranges):
    assert Pattern.LEUKOCYTOSIS in _patterns(ranges, wbc=12.0, neut_pct=82.0)
    assert Pattern.LEUKOCYTOSIS not in _patterns(ranges, wbc=12.0)
    assert _patterns(ranges, wbc=2.8)[0] is Pattern.LEUKOPENIA


def test_three_unmatched_abnormalities_fall_back_to_multi(ranges):
    patterns = _patterns(ranges, rbc=6.2, hct=52.0, rdw=17.0)
    assert patterns == [Pattern.MULTI_ABNORMAL]


def test_one_unmatched_abnormality_is_single(ranges):
    """1 项异常且不匹配任何模式：单列成 SINGLE_ABNORMAL，不硬塞 MULTI_ABNORMAL。"""
    assert _patterns(ranges, hct=52.0) == [Pattern.SINGLE_ABNORMAL]


def test_two_unmatched_abnormalities_are_mixed(ranges):
    """2 项异常且不匹配任何组合：MIXED_ABNORMAL（与单项异常分开统计）。"""
    assert _patterns(ranges, hct=52.0, rdw=17.0) == [Pattern.MIXED_ABNORMAL]


def test_single_and_mixed_labels_differ(ranges):
    assert Pattern.SINGLE_ABNORMAL.text_cn != Pattern.MIXED_ABNORMAL.text_cn


def test_detect_patterns_ignores_na(ranges):
    verdict = judge_sample(
        {**BASE, "hgb": None}, sample_index=0, gender="male", age=30, ranges=ranges
    )
    assert detect_patterns(verdict.flags) == [Pattern.NORMAL]
