"""P2-②：热力图的 ρ 必须带上它自己的样本量 n。

ρ 是"这两列都非空的那批人"算出来的，各对并不相同。只写 ρ 不写 n，读者会把
n = 94 的 0.93 和 n = 40 的 0.93 当成同等证据——而后者在 95% 置信水平下根本不显著。
"""

from __future__ import annotations

import pandas as pd

from app.pipeline.stats import correlation
from app.services.chart import corr_chart


def _frame(rows: int = 12, *, holes: int = 0) -> pd.DataFrame:
    data = {
        "hgb": [120 + index * 3 for index in range(rows)],
        "rbc": [4.0 + index * 0.05 for index in range(rows)],
        "mcv": [80 + index for index in range(rows)],
        "mch": [25 + index * 0.5 for index in range(rows)],
    }
    frame = pd.DataFrame(data)
    if holes:
        # 让 mcv 缺几个：与 mcv 有关的那些对 n 会变小
        frame.loc[frame.index[:holes], "mcv"] = None
    return frame


def _cells(payload: dict) -> dict[tuple[int, int], dict]:
    data = payload["echarts_option"]["series"][0]["data"]
    return {(item["value"][0], item["value"][1]): item for item in data}


def test_each_cell_carries_its_own_n(fields) -> None:
    frame = _frame()
    payload = corr_chart(frame, fields, correlation(frame, fields))
    cells = _cells(payload)
    names = payload["echarts_option"]["xAxis"]["data"]

    # 取两个非对角格子，n 应当等于参与计算的行数（12）
    sample = next(item for (x, y), item in cells.items() if x != y)
    assert "n = 12" in sample["name"]
    # 名字里是"全名 × 全名：ρ = …（n = …）"，短名只在轴上
    assert "×" in sample["name"]
    assert names  # 轴上是短名，与 name 里的全名分工不同


def test_uniform_sample_size_keeps_subtext_silent(fields) -> None:
    frame = _frame()
    payload = corr_chart(frame, fields, correlation(frame, fields))
    assert "各格样本量不同" not in payload["echarts_option"]["title"]["subtext"]
    assert payload["supporting"]["n_min"] == payload["supporting"]["n_max"] == 12
    assert payload["supporting"]["n_note"] == ""


def test_varying_sample_size_is_announced(fields) -> None:
    frame = _frame(holes=3)
    payload = corr_chart(frame, fields, correlation(frame, fields))
    subtext = payload["echarts_option"]["title"]["subtext"]
    assert "各格样本量不同" in subtext
    assert payload["supporting"]["n_note"].startswith("各格样本量不同")
    assert payload["supporting"]["n_min"] < payload["supporting"]["n_max"]
    # 与 mcv 相关的那几格 n 更小
    cells = _cells(payload)
    x_index = payload["echarts_option"]["xAxis"]["data"].index("MCV")
    y_index = 0  # HGB 在第 0 行
    assert "n = 9" in cells[(x_index, y_index)]["name"]
