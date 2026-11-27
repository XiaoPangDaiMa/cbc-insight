"""BR-23：五分类绝对值与百分比的交叉校验（只报不良，不改数据）。

这一条的全部价值在于"能发现整列错位"：五个百分比列各自都在 0–100 的合法区间里，
交换 NE# 与 LY# 之后每一列看起来都正常，只有"绝对值 = WBC × 百分比"这条算术关系
会当场崩掉。所以测试要证明的也只有一件事：**对得上时不吵，对不上时抓得住。**
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.pipeline.cleaning import clean
from app.pipeline.validators import (
    CHECK_ABSOLUTE_FLOOR,
    find_check_violations,
    validate,
)


def _numeric(**overrides: float) -> pd.DataFrame:
    base = {
        "wbc": 7.0,
        "neut_pct": 60.0,
        "lymph_pct": 30.0,
        "mono_pct": 7.0,
        "eo_pct": 2.0,
        "baso_pct": 1.0,
        "neut_abs": 4.2,
        "lymph_abs": 2.1,
        "mono_abs": 0.49,
        "eo_abs": 0.14,
        "baso_abs": 0.07,
    }
    base.update(overrides)
    return pd.DataFrame([base])


def test_consistent_absolute_counts_pass() -> None:
    assert find_check_violations(_numeric()) == {}


def test_swapped_columns_are_caught() -> None:
    """NE# 与 LY# 互换：两列各自合法，只有复算能发现。"""
    swapped = _numeric(neut_abs=2.1, lymph_abs=4.2)
    violations = find_check_violations(swapped)
    assert set(violations) == {"neut_abs", "lymph_abs"}
    assert violations["neut_abs"] == (0,)
    assert violations["lymph_abs"] == (0,)


def test_small_counts_are_not_flagged_by_rounding() -> None:
    """EO# 常保留 1 位小数，0.1 与 0.035 的"相对误差"是 186%——不能算错。"""
    rounded = _numeric(eo_pct=0.5, eo_abs=CHECK_ABSOLUTE_FLOOR)
    assert find_check_violations(rounded) == {}


def test_real_deviation_on_large_counts_is_flagged() -> None:
    big = _numeric(eo_pct=5.0, eo_abs=0.5)  # 应 0.35，差 0.15 > max(15%, 0.1)
    assert find_check_violations(big) == {"eo_abs": (0,)}


def test_absent_absolute_columns_are_skipped() -> None:
    """只有百分比、没有绝对值的导出表是常态，不能因此报错。"""
    numeric = pd.DataFrame([{"wbc": 7.0, "neut_pct": 60.0, "lymph_pct": 30.0}])
    assert find_check_violations(numeric) == {}


def test_missing_wbc_makes_the_check_impossible() -> None:
    numeric = _numeric().drop(columns=["wbc"])
    assert find_check_violations(numeric) == {}


def test_br23_does_not_change_dq05(fields, mapping_config) -> None:
    """BR-23 只报不良：加不加绝对值列，DQ-05 必须完全一样。"""
    rows = []
    for index in range(6):
        row = {
            "age": 40 + index,
            "gender": "male",
            "wbc": 7.0,
            "rbc": 5.0,
            "hgb": 150.0,
            "hct": 45.0,
            "mcv": 90.0,
            "mch": 30.0,
            "mchc": 333.0,
            "plt": 250.0,
            "neut_pct": 60.0,
            "lymph_pct": 30.0,
            "mono_pct": 7.0,
            "eo_pct": 2.0,
            "baso_pct": 1.0,
        }
        rows.append(row)
    without_abs = pd.DataFrame(rows)
    with_abs = without_abs.assign(
        neut_abs=4.2, lymph_abs=2.1, mono_abs=0.49, eo_abs=0.14, baso_abs=0.07
    )
    # 故意把一行写错，确认问题被报出来、但质量分不受影响
    with_abs.loc[3, "neut_abs"] = 1.0

    _, plain = validate(without_abs, fields)
    validated, flagged = validate(with_abs, fields)

    assert "DQ-05" in plain.dq and plain.dq["DQ-05"] == flagged.dq["DQ-05"]
    assert validated.check_violations.get("neut_abs") == (3,)
    issues = [issue for issue in flagged.issues if issue.code == "BR-23"]
    assert len(issues) == 1
    assert issues[0].severity == "WARN"
    assert issues[0].field == "neut_abs"
    # 只报不改：任何一列都不该被置空
    cleaned = clean(with_abs, validated, fields, mapping_config)
    assert cleaned.frame.loc[3, "neut_abs"] == pytest.approx(1.0)


def test_cleaning_does_not_impute_check_only_fields(fields, mapping_config) -> None:
    """填充绝对值等于替用户编一份"对的"绝对值，校验会立刻全绿。

    缺 1/6（16.7%）不会触发"缺失率 >30% 整列剔除"，所以列会留下——
    正好用来看它是不是被中位数填上了。
    """
    rows = []
    for index in range(6):
        row = {
            "age": 40 + index,
            "gender": "male",
            "hgb": 150.0 - index,
            "wbc": 7.0,
            "plt": 250.0,
            "neut_pct": 60.0,
            "neut_abs": 4.2,
        }
        rows.append(row)
    rows[1].pop("neut_abs")  # 只缺一行
    frame = pd.DataFrame(rows)

    validated, _report = validate(frame, fields)
    cleaned = clean(frame, validated, fields, mapping_config)
    assert "neut_abs" in cleaned.frame.columns
    assert pd.isna(cleaned.frame.loc[1, "neut_abs"])
