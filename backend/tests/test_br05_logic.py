"""BR-05 逻辑一致性：``|hct − rbc × mcv / 10| / hct > 15%`` → hct 置空。"""

from __future__ import annotations

import pandas as pd

from app.pipeline.cleaning import clean
from app.pipeline.validators import find_logic_violations, validate


def _frame(hct: float, rbc: float = 4.0, mcv: float = 80.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gender": ["male"],
            "age": [30],
            "hgb": [140],
            "wbc": [6.0],
            "plt": [200],
            "hct": [hct],
            "rbc": [rbc],
            "mcv": [mcv],
        }
    )


def test_consistent_triplet_is_not_flagged(fields):
    # 4.0 × 80 / 10 = 32.0，与 hct 完全一致
    validated, _ = validate(_frame(hct=32.0), fields)
    assert find_logic_violations(validated.numeric) == ()


def test_deviation_within_tolerance_is_not_flagged(fields):
    # 偏差 10% < 15%
    validated, _ = validate(_frame(hct=35.2), fields)
    assert validated.logic_violations == ()


def test_large_deviation_nulls_hct(fields, mapping_config):
    frame = _frame(hct=60.0)  # 偏差 87.5%
    validated, _ = validate(frame, fields)
    assert validated.logic_violations == (0,)
    result = clean(frame, validated, fields, mapping_config)
    assert result.frame["hct"].isna().all() or pd.isna(result.frame.loc[0, "hct"])


def test_logic_violation_does_not_remove_the_row(fields, mapping_config):
    """BR-06：逻辑矛盾只置空 hct，整行仍保留（其他指标仍有效）。"""
    frame = _frame(hct=60.0)
    validated, _ = validate(frame, fields)
    result = clean(frame, validated, fields, mapping_config)
    assert len(result.frame) == 1


def test_partial_fields_are_not_judged(fields):
    frame = _frame(hct=60.0)
    frame["mcv"] = None  # 三字段不齐 → 无法判，不算违规
    validated, _ = validate(frame, fields)
    assert validated.logic_violations == ()
