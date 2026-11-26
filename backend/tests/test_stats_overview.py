"""指标总览的展示口径：偏离度封顶、实测/填充计数。

窄区间上偏离度能到四位数（``baso_pct`` 区间宽 1，34.4% 就是 3440%），数字没错但
"最大偏离 3440%"读起来像 bug，所以展示层封顶并用 ≥ 表达，同时保留原始值备查。
"""

from __future__ import annotations

import pandas as pd

from app.pipeline import rules
from app.pipeline.stats import MAX_DEVIATION_DISPLAY, metric_overview
from app.services.loader import load_fields, load_reference_ranges


def _overview(metric: str, values: list[float]) -> dict:
    fields = load_fields()
    ranges = load_reference_ranges()
    frame = pd.DataFrame(
        {
            "sample_index": list(range(len(values))),
            "gender": ["male"] * len(values),
            "age": [40.0] * len(values),
            "age_band": ["40-49"] * len(values),
            metric: values,
        }
    )
    long, _ = rules.flag_frame(frame, ranges)
    items = metric_overview(frame, long, fields, ranges=ranges)
    return next(item for item in items if item["metric"] == metric)


def test_deviation_is_capped_for_display() -> None:
    item = _overview("baso_pct", [0.6] * 20 + [34.0])

    assert item["max_deviation_capped"] is True
    assert item["max_deviation_pct"] == MAX_DEVIATION_DISPLAY
    # 原始值仍然在（报告与排查要用），且确实远大于展示上限
    assert item["max_deviation_pct_raw"] > 3000


def test_deviation_is_not_capped_when_distribution_is_normal() -> None:
    item = _overview("hgb", [138.0, 140.0, 142.0, 145.0, 150.0, 160.0, 170.0, 172.0])

    assert item["max_deviation_capped"] is False
    assert item["max_deviation_pct"] == item["max_deviation_pct_raw"]
