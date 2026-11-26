"""BR-05 逻辑一致性：三条恒等式对不上时，把被证伪的那一列置空。

* ``HCT ≈ RBC × MCV / 10``
* ``MCH = HGB / RBC``
* ``MCHC = HGB / HCT``

后两条是**定义式**：只要 HGB / RBC / HCT 里有一个数错，或者整列错位一格，它们立刻
对不上。这是抓"列错位"最便宜的办法，不需要额外数据也不需要模型。
"""

from __future__ import annotations

import pandas as pd

from app.pipeline.cleaning import clean
from app.pipeline.validators import find_logic_violations, validate


def _frame(hct: float = 32.0, rbc: float = 4.0, mcv: float = 80.0, hgb: float = 140.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gender": ["male"],
            "age": [30],
            "hgb": [hgb],
            "wbc": [6.0],
            "plt": [200],
            "hct": [hct],
            "rbc": [rbc],
            "mcv": [mcv],
            # 4.0 × 80 / 10 = 32；MCH = 140/4 = 35；MCHC = 140/0.32 = 437.5
            "mch": [35.0],
            "mchc": [437.5],
        }
    )


def test_consistent_triplet_is_not_flagged(fields):
    validated, _ = validate(_frame(), fields)
    assert find_logic_violations(validated.numeric) == {}


def test_deviation_within_tolerance_is_not_flagged(fields):
    # HCT 差 10% < 15%
    validated, _ = validate(_frame(hct=35.2), fields)
    assert validated.identity_violations == {}


def test_large_deviation_nulls_hct(fields, mapping_config):
    frame = _frame(hct=60.0)  # HCT 与 32 差 87.5%
    validated, _ = validate(frame, fields)
    assert validated.identity_violations["hct"] == (0,)
    result = clean(frame, validated, fields, mapping_config)
    assert pd.isna(result.frame.loc[0, "hct"])


def test_logic_violation_does_not_remove_the_row(fields, mapping_config):
    """BR-06：逻辑矛盾只置空被证伪的那一列，整行仍保留（其他指标仍有效）。"""
    frame = _frame(hct=60.0)
    validated, _ = validate(frame, fields)
    result = clean(frame, validated, fields, mapping_config)
    assert len(result.frame) == 1


def test_partial_fields_are_not_judged(fields):
    frame = _frame(hct=60.0)
    frame["mcv"] = None  # 三字段不齐 → 无法判，不算违规
    validated, _ = validate(frame, fields)
    assert "hct" not in validated.identity_violations


def test_mch_identity_catches_column_shift(fields, mapping_config):
    """MCH 写错（例如整列错位一格）：HGB 与 RBC 都正常，只有 MCH 对不上。"""
    frame = _frame()
    frame["mch"] = [22.0]  # 应为 35，差 37%
    validated, _ = validate(frame, fields)
    assert validated.identity_violations["mch"] == (0,)
    assert "hct" not in validated.identity_violations

    result = clean(frame, validated, fields, mapping_config)
    assert pd.isna(result.frame.loc[0, "mch"])
    # 证据字段（hgb / rbc）不能跟着被删，否则看不出"哪里错了"
    assert result.frame.loc[0, "hgb"] == 140


def test_mchc_identity_catches_hct_error(fields):
    frame = _frame()
    frame["mchc"] = [300.0]  # 应为 437.5，差 31%
    validated, _ = validate(frame, fields)
    assert validated.identity_violations["mchc"] == (0,)


def test_zero_denominator_is_skipped(fields):
    """RBC = 0 时 MCH 无定义——这是"无法判"，不是"有问题"。"""
    frame = _frame(rbc=0.0)
    frame["mch"] = [0.0]
    validated, _ = validate(frame, fields)
    assert "mch" not in validated.identity_violations
