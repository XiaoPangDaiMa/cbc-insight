"""BR-03 缺失处理：整列剔除、核心字段全空删行、分组中位数填充。"""

from __future__ import annotations

import pandas as pd

from app.pipeline.cleaning import clean
from app.pipeline.validators import validate


def _clean(frame: pd.DataFrame, fields, mapping_config):
    validated, report = validate(frame, fields)
    return clean(frame, validated, fields, mapping_config), report


def test_column_with_high_missing_rate_is_dropped(fields, mapping_config):
    frame = pd.DataFrame(
        {
            "gender": ["male", "male", "male", "male"],
            "age": [30, 31, 32, 33],
            "hgb": [140, 141, 142, 143],
            "wbc": [6, 6, 6, 6],
            "plt": [200, 210, 220, 230],
            "rdw": [None, None, 12.5, None],
        }
    )
    result, report = _clean(frame, fields, mapping_config)
    assert "rdw" in result.dropped_columns
    assert "rdw" not in result.frame.columns
    assert any(issue.code == "BR-03" and issue.field == "rdw" for issue in report.issues)


def test_row_with_all_core_fields_empty_is_removed(fields, mapping_config):
    frame = pd.DataFrame(
        {
            "gender": ["male", "male", "male"],
            "age": [30, 31, 32],
            "hgb": [140, None, 150],
            "wbc": [6, None, 7],
            "plt": [200, None, 210],
            "rbc": [4.8, 4.5, 5.0],
        }
    )
    result, _ = _clean(frame, fields, mapping_config)
    assert result.removed_by_reason.get("core_all_null") == 1
    assert len(result.frame) == 2


def test_missing_filled_by_gender_and_age_band_median(fields, mapping_config):
    frame = pd.DataFrame(
        {
            "gender": ["male", "male", "female", "female"],
            "age": [25, 26, 35, 36],
            "hgb": [140, None, 120, None],
            "wbc": [6, 6, 6, 6],
            "plt": [200, 200, 200, 200],
        }
    )
    result, _ = _clean(frame, fields, mapping_config)
    hgb = result.frame["hgb"].tolist()
    assert hgb[1] == 140  # 男性 18-29 组中位数
    assert hgb[3] == 120  # 女性 30-39 组中位数
    assert result.filled.get("hgb") == 2


def test_fill_falls_back_to_overall_median_when_group_has_no_value(fields, mapping_config):
    frame = pd.DataFrame(
        {
            "gender": ["male", "female"],
            "age": [25, 35],
            "hgb": [None, 130],
            "wbc": [6, 6],
            "plt": [200, 200],
        }
    )
    result, _ = _clean(frame, fields, mapping_config)
    assert result.frame["hgb"].tolist()[0] == 130
