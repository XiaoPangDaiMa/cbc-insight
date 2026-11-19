"""BR-09 年龄段划分。"""

from __future__ import annotations

import pytest

from app.pipeline.derive import age_band


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (17, "minor"),
        (18, "18-29"),
        (25, "18-29"),
        (29, "18-29"),
        (30, "30-39"),
        (39, "30-39"),
        (40, "40-49"),
        (49, "40-49"),
        (50, "50-59"),
        (59, "50-59"),
        (60, "60+"),
        (79, "60+"),
    ],
)
def test_age_band_boundaries(age, expected):
    assert age_band(age) == expected


def test_missing_age_is_its_own_band():
    """BR-17：age 缺失不并入任何年龄段。"""
    assert age_band(None) == "Unknown"
    assert age_band(float("nan")) == "Unknown"


def test_age_band_is_added_by_pipeline(pipeline, clean_csv):
    result = pipeline(clean_csv)
    assert "age_band" in result.frame.columns
    assert set(result.frame["age_band"]) <= {"18-29", "30-39", "40-49", "50-59", "60+", "minor", "Unknown"}
