"""箱线图须端与直方图分箱的形态测试（A+B 两处修复的回归）。

这两条不是"图好不好看"的审美问题，而是**读者会不会得出错结论**：

* 须端取 min/max 时，一个 34% 的嗜碱性粒细胞值就把 y 轴拉到 34，箱体被压成一条线，
  看图的人会以为"这一组全是 0"；其实 Q1–Q3 正常，只是被极值掩盖了。
* 等宽 20 桶铺满全域时，第一桶吃掉 9.2 万条、后面 19 桶全空，
  看图的人会以为"数据只有一档"，而尾部那 4% 才是异常样本所在。
"""

from __future__ import annotations

import pandas as pd

from app.pipeline import rules
from app.services.chart import box_chart, hist_chart
from app.services.loader import load_fields, load_reference_ranges


def _frame(metric: str, values: list[float], gender: str = "male") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample_index": list(range(len(values))),
            "gender": [gender] * len(values),
            "age": [40] * len(values),
            metric: values,
        }
    )


def _charts(metric: str, values: list[float]):
    fields = load_fields()
    ranges = load_reference_ranges()
    frame = _frame(metric, values)
    long, _summary = rules.flag_frame(frame, ranges)
    return (
        box_chart(frame, long, fields, ranges, metric),
        hist_chart(frame, long, fields, ranges, metric),
    )


def test_box_whisker_stops_at_1_5_iqr_not_max() -> None:
    """须端 = 1.5×IQR 内的最远观测值；外面那个 100 不把轴拉满。

    100 既没被丢掉、也没有被画进主图：它超出显示窗口，只在副标题里报数。
    这是刻意的取舍——把它画进来，y 轴就会到 100，箱体（1–20）又被压成一条线，
    而"箱体被压成一条线"正是这次要修的现象本身。
    """
    values = [float(v) for v in range(1, 21)] + [100.0]
    box, _ = _charts("hgb", values)

    five = box["echarts_option"]["series"][0]["data"][0]
    whisker_low, _q1, _median, _q3, whisker_high = five
    assert whisker_high == 20.0, f"须端应停在 20，实际 {whisker_high}"
    assert whisker_low == 1.0

    axis = box["echarts_option"]["yAxis"]
    # 窗口上界 = Q3 + 3×IQR ≈ 46，比极值 100 低得多，箱体（1–20）因此还看得见
    assert axis["max"] < 60, f"轴不该被 100 拉满，实际 {axis['max']}"

    # 100 没被丢掉：计数写进副标题，最大值也报出来（BR-06：异常值不是脏数据）
    assert box["supporting"]["groups"]["male"]["outliers"] == 1
    subtext = box["echarts_option"]["title"]["subtext"]
    assert "离群点 1 个" in subtext
    assert "超出显示范围未画出" in subtext
    assert "100" in subtext
    # 窗口外的点不画，因此不会多出一条空散点系列
    assert len(box["echarts_option"]["series"]) == 1


def test_box_near_outlier_is_drawn_as_scatter() -> None:
    """落在显示窗口内的离群点画成散点，不只报数——否则读者会以为数据只到须端。"""
    # 主体全为 0（IQR=0），窗口退化为真实极值，1.0 与 1.2 都在窗口内
    values = [0.0] * 20 + [1.0, 1.2]
    box, _ = _charts("baso_pct", values)

    scatter = box["echarts_option"]["series"][1]
    assert scatter["type"] == "scatter"
    assert [point[1] for point in scatter["data"]] == [1.0, 1.2]
    assert "超出显示范围" not in box["echarts_option"]["title"]["subtext"]


def test_box_flat_group_does_not_crash() -> None:
    """整组相同（IQR=0）时须长为 0，但图必须能画出来。"""
    box, _ = _charts("baso_pct", [0.6] * 30)
    five = box["echarts_option"]["series"][0]["data"][0]
    assert five[0] == five[4] == five[2] == 0.6
    assert "series" in box["echarts_option"]
    assert len(box["echarts_option"]["series"]) == 1  # 没有离群点就不该多一条空散点


def test_hist_zero_bucket_and_display_window() -> None:
    """零值堆积单独一桶；长尾用 Q3+3×IQR 收住，窗口外的量单独计数。

    数据形状照着 DS-02 的 `baso_pct` 仿造：96% 是 0，大量小值，尾巴上有一个 34%。
    """
    body = [0.1 + 0.0045 * index for index in range(200)]  # 0.1 … 1.0
    values = [0.0] * 300 + body + [34.0]
    _, hist = _charts("baso_pct", values)

    bins = hist["supporting"]["bins"]
    assert bins["zero_bucket"] is True
    assert bins["labels"][0] == "0"
    assert bins["counts"][0] == 300

    low, high = bins["window"]
    assert low == 0.1
    assert high < 5.0, f"窗口应被长尾收住，实际到 {high}"
    # 34 落在 Q3+3×IQR 之外 → 计入"超出显示范围"，而不是被静默丢掉
    assert bins["outside_count"] >= 1
    assert bins["outside_max"] == 34.0

    subtext = hist["echarts_option"]["title"]["subtext"]
    assert "超出显示范围" in subtext
    assert "0 值单列一桶" in subtext

    # 桶数 = 按样本量算出的桶数 + 至多一个零值桶，不会因为长尾炸成几十格
    expected_bins = max(20, min(48, int(len(values) ** 0.5)))
    assert len(bins["labels"]) <= expected_bins + 1
    # 每个样本都有归属：桶内 + 窗口外 == 总样本数
    assert sum(bins["counts"]) + bins["outside_count"] == len(values)


def test_hist_bins_scale_with_sample_size() -> None:
    """桶数按 √n 取，并夹在 20–48 之间：小数据别碎成沙，大数据别挤成两根柱子。"""
    small = [130.0 + index * 0.5 for index in range(100)]  # √100 = 10 → 夹到 20
    _, hist_small = _charts("hgb", small)
    assert len(hist_small["supporting"]["bins"]["labels"]) == 20

    large = [130.0 + (index % 400) * 0.1 for index in range(5000)]  # √5000 ≈ 70 → 夹到 48
    _, hist_large = _charts("hgb", large)
    assert len(hist_large["supporting"]["bins"]["labels"]) == 48


def test_hist_without_zero_inflation_keeps_full_range() -> None:
    """没有零值堆积的指标（血红蛋白）不该被硬塞一个"0"桶。"""
    values = [130.0, 132.0, 135.0, 138.0, 140.0, 142.0, 145.0, 150.0, 155.0, 160.0]
    _, hist = _charts("hgb", values)
    bins = hist["supporting"]["bins"]
    assert bins["zero_bucket"] is False
    assert bins["labels"][0].startswith("130")
    assert sum(bins["counts"]) == len(values)
