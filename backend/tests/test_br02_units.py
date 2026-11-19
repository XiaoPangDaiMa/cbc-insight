"""BR-02 单位归一：中位数判据、换算留痕、模糊带不猜测。"""

from __future__ import annotations

import pandas as pd

from app.pipeline.units import SCALE_RULES, detect_unit


def test_gdl_hemoglobin_is_scaled_by_ten():
    # T-07：hgb 中位数 14.2 → 判为 g/dL，×10 归一
    series = pd.Series([13.8, 14.2, 15.1, 14.9, 13.5])
    decision = detect_unit("hgb", series)
    assert decision.detected_unit == "g/dL"
    assert decision.factor == 10.0
    assert decision.converted is True
    assert "g/dL" in decision.log_line()


def test_gl_hemoglobin_is_left_alone():
    series = pd.Series([138, 142, 151, 149, 135])
    decision = detect_unit("hgb", series)
    assert decision.detected_unit == "g/L"
    assert decision.factor == 1.0
    assert decision.log_line() == ""


def test_ambiguous_band_is_not_guessed():
    series = pd.Series([60.0, 62.0, 65.0, 70.0])
    decision = detect_unit("hgb", series)
    assert decision.ambiguous is True
    assert decision.factor == 1.0
    assert decision.converted is False
    assert set(decision.candidates) == {"g/dL", "g/L"}


def test_wbc_per_microlitre_scaled_down():
    series = pd.Series([6200, 6800, 7100, 5900])
    decision = detect_unit("wbc", series)
    assert decision.detected_unit == "个/µL"
    assert decision.factor == 0.001


def test_rbc_wan_per_microlitre_scaled_down():
    """万/µL → ×10¹²/L 的系数是 ÷100（1×10¹²/L = 100 万/µL）。"""
    series = pd.Series([480, 510, 495, 470])
    decision = detect_unit("rbc", series)
    assert decision.detected_unit == "万/µL"
    assert decision.factor == 0.01


def test_forced_unit_overrides_detection():
    series = pd.Series([60.0, 62.0])
    decision = detect_unit("hgb", series, forced_unit="g/L")
    assert decision.ambiguous is False
    assert decision.factor == 1.0


def test_every_rule_has_a_clear_upper_or_lower_band():
    for metric, rules in SCALE_RULES.items():
        assert rules[0][0] == 0, f"{metric} 第一档必须从 0 开始"
        assert rules[-1][1] is None, f"{metric} 最后一档必须无上界"
