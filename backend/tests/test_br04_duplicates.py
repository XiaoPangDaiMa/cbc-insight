"""BR-04 重复判定：全字段完全一致视为重复，保留首条。"""

from __future__ import annotations

import pandas as pd

from app.pipeline.cleaning import clean
from app.pipeline.validators import validate


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gender": ["male", "male", "female"],
            "age": [30, 30, 30],
            "hgb": [140, 140, 125],
            "wbc": [6.0, 6.0, 5.5],
            "plt": [200, 200, 210],
        }
    )


def test_duplicate_rows_detected_keep_first(fields):
    validated, _ = validate(_frame(), fields)
    assert validated.duplicate_rows == (1,)


def test_duplicate_rows_removed_and_counted(fields, mapping_config):
    frame = _frame()
    validated, _ = validate(frame, fields)
    result = clean(frame, validated, fields, mapping_config)
    assert len(result.frame) == 2
    assert result.removed_by_reason.get("duplicate") == 1
    assert result.frame["gender"].tolist() == ["male", "female"]


def test_near_duplicate_is_not_duplicate(fields, mapping_config):
    frame = _frame()
    frame.loc[1, "hgb"] = 141  # 只差一个字段
    validated, _ = validate(frame, fields)
    assert validated.duplicate_rows == ()


def test_fixture_has_exactly_one_duplicate(pipeline, clean_csv):
    result = pipeline(clean_csv)
    assert result.cleaned.removed_by_reason.get("duplicate") == 1
    assert len(result.frame) == 8
