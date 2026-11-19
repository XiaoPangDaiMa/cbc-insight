"""服务端静态渲染（FR-20 图表导出、FR-21 报告内嵌图、4.3.4 双渲染通道）。

为什么要有第二套渲染：屏幕上的 ECharts 图是 DOM 画出来的，用户"导出报告"时不能靠截图
（字体、dpi、滚动位置都会变）。这里用 matplotlib 把同一份数据重新画一遍，产出 300 dpi
的 PNG 与矢量 SVG——报告进 Word/PDF、答辩投影、论文排版都用它。

**颜色只能来自 ``backend/resources/theme.json``**（由 ``scripts/gen_theme.py`` 从
``frontend/src/theme/tokens.json`` 生成）。本模块不出现任何字面十六进制色值，
否则屏幕图与报告图会各自漂移（NFR-M-07、RK-22、RK-23）。
"""

from __future__ import annotations

import functools
import io
import json
from pathlib import Path
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")  # 必须在 pyplot 之前：无显示环境（服务器/CI）也能出图

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.core.config import get_settings  # noqa: E402

Format = Literal["png", "svg"]

# 中文字体必须显式给候选列表：DejaVu 不含汉字，缺字体会把标题画成方框（RK-05）
CJK_FONTS = ("Microsoft YaHei", "SimHei", "Noto Sans SC", "DengXian", "DejaVu Sans")

STATUS_COLOR_KEY = {
    "LOW": "status_low",
    "NORMAL": "status_normal",
    "HIGH": "status_high",
    "NA": "status_na",
}


@functools.lru_cache(maxsize=1)
def _theme() -> dict[str, Any]:
    path = Path(get_settings().resources_dir) / "theme.json"
    if not path.is_file():
        raise RuntimeError("缺少 backend/resources/theme.json，请先运行 python scripts/gen_theme.py")
    return json.loads(path.read_text(encoding="utf-8"))


def colors() -> dict[str, str]:
    return _theme()["color"]


def series_colors() -> list[str]:
    return list(_theme()["chart"]["series"])


def status_color(status: str) -> str:
    return colors()[STATUS_COLOR_KEY.get(status, "status_na")]


def _apply_style() -> None:
    """每次出图前把 rcParams 重置成项目样式，避免上一个图的设置泄漏到下一个。

    颜色一律走 ``theme.json``：``cbc.mplstyle`` 里不写色值（matplotlibrc 把 ``#`` 当注释，
    十六进制色会被截断成空串）。这样屏幕与报告仍然只有一个配色来源（NFR-M-07）。
    """
    style = Path(get_settings().resources_dir) / "cbc.mplstyle"
    plt.rcdefaults()
    if style.is_file():
        plt.style.use(str(style))
    palette = colors()
    plt.rcParams.update(
        {
            "figure.facecolor": palette["bg_surface"],
            "axes.facecolor": palette["bg_surface"],
            "savefig.facecolor": palette["bg_surface"],
            "text.color": palette["text_primary"],
            "axes.labelcolor": palette["text_secondary"],
            "axes.edgecolor": palette["border"],
            "xtick.color": palette["text_secondary"],
            "ytick.color": palette["text_secondary"],
            "grid.color": palette["grid"],
            "axes.prop_cycle": plt.cycler(color=series_colors()),
        }
    )
    plt.rcParams["font.sans-serif"] = list(CJK_FONTS)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False


def _to_bytes(fig, fmt: str) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format=fmt, bbox_inches="tight", dpi=300)
    plt.close(fig)
    buffer.seek(0)
    return buffer.read()


def _band_lines(ax, bands: list[dict], decimals: int, *, vertical: bool = False) -> None:
    """参考区间：男性虚线、女性点线；两条都画，避免"没性别就装作只有一条"。

    ``vertical=True`` 用于直方图（横轴才是实测值）。这里必须是竖线——画成横线会把
    纵轴（样本数）撑到参考上下限的量级，柱子被压成贴着底边的一条，图就废了。
    """
    for band in bands:
        is_female = band.get("gender") == "female"
        style = ":" if is_female else "--"
        label = "女" if is_female else "男"
        low_color = colors()["status_low"]
        high_color = colors()["status_high"]
        if vertical:
            for value, color, text in (
                (band["low"], low_color, f"{label}下限 {band['low']:.{decimals}f}"),
                (band["high"], high_color, f"{label}上限 {band['high']:.{decimals}f}"),
            ):
                ax.axvline(value, linestyle=style, linewidth=1.2, color=color)
                ax.annotate(
                    text,
                    xy=(value, 0.995),
                    xycoords=ax.get_xaxis_transform(),
                    xytext=(2, 0),
                    textcoords="offset points",
                    rotation=90,
                    ha="left",
                    va="top",
                    fontsize=7.5,
                    color=colors()["text_secondary"],
                )
            continue
        ax.axhline(band["low"], linestyle=style, linewidth=1.2, color=low_color)
        ax.axhline(band["high"], linestyle=style, linewidth=1.2, color=high_color)
        ax.text(
            1.01,
            band["low"],
            f"{label}下限 {band['low']:.{decimals}f}",
            transform=ax.get_yaxis_transform(),
            va="center",
            fontsize=8,
            color=colors()["text_secondary"],
        )
        ax.text(
            1.01,
            band["high"],
            f"{label}上限 {band['high']:.{decimals}f}",
            transform=ax.get_yaxis_transform(),
            va="center",
            fontsize=8,
            color=colors()["text_secondary"],
        )


def box_image(
    long: pd.DataFrame,
    metric: str,
    *,
    name_cn: str,
    unit: str,
    bands: list[dict],
    decimals: int = 2,
    fmt: Format = "png",
) -> bytes:
    """按性别分组的箱线图（每组标注 n + 参考区间线）。"""
    _apply_style()
    subset = long[(long["metric"] == metric) & long["value"].notna()]
    fig, ax = plt.subplots(figsize=(6.2, 4.0))

    groups: list[tuple[str, np.ndarray]] = []
    for gender, label in (("male", "男"), ("female", "女")):
        values = subset.loc[subset["gender"] == gender, "value"].to_numpy(dtype=float)
        if values.size:
            groups.append((f"{label}（n = {values.size}）", values))
    if not groups:
        values = subset["value"].to_numpy(dtype=float)
        groups.append((f"全部（n = {values.size}）", values))

    data = [values for _, values in groups]
    boxes = ax.boxplot(
        data,
        patch_artist=True,
        widths=0.5,
        medianprops={"color": colors()["text_primary"], "linewidth": 1.6},
        flierprops={
            "marker": "o",
            "markersize": 3,
            "markerfacecolor": colors()["text_muted"],
            "markeredgecolor": "none",
        },
    )
    for index, patch in enumerate(boxes["boxes"]):
        color = series_colors()[index % len(series_colors())]
        patch.set_facecolor(color)
        patch.set_alpha(0.35)
        patch.set_edgecolor(color)
    ax.set_xticks(range(1, len(groups) + 1))
    ax.set_xticklabels([label for label, _ in groups])
    _band_lines(ax, bands, decimals)
    ax.set_ylabel(f"{name_cn}（{unit}）" if unit else name_cn)
    ax.set_title(f"{name_cn} 分布（按性别分组）", fontsize=12, loc="left")
    return _to_bytes(fig, fmt)


def hist_image(
    long: pd.DataFrame,
    metric: str,
    *,
    name_cn: str,
    unit: str,
    bands: list[dict],
    decimals: int = 2,
    bins: int = 20,
    fmt: Format = "png",
) -> bytes:
    """直方图 + 参考区间线；柱子按"该指标整体判定"着色容易误导，这里用单色。"""
    _apply_style()
    subset = long[(long["metric"] == metric) & long["value"].notna()]
    values = subset["value"].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    ax.hist(values, bins=bins, color=series_colors()[0], alpha=0.75, edgecolor="white")
    _band_lines(ax, bands, decimals, vertical=True)
    ax.set_xlabel(f"{name_cn}（{unit}）" if unit else name_cn)
    ax.set_ylabel("样本数")
    ax.margins(x=0.02)
    ax.set_title(f"{name_cn} 分布（n = {values.size}）", fontsize=12, loc="left")
    return _to_bytes(fig, fmt)


def corr_image(stats_payload: dict, *, fmt: Format = "png") -> bytes:
    """相关性热力图（Spearman）。格内写 ρ，便于黑白打印时读数（BR-14 的三通道思想）。"""
    _apply_style()
    matrix = stats_payload.get("matrix") or {}
    metrics = list(stats_payload.get("metrics") or [])
    if not matrix or not metrics:
        raise ValueError("相关性数据为空")
    data = np.array([[matrix.get(a, {}).get(b, np.nan) for b in metrics] for a in metrics], dtype=float)

    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    mesh = ax.imshow(data, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(metrics)))
    ax.set_yticks(range(len(metrics)))
    ax.set_xticklabels([m.upper() for m in metrics], rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels([m.upper() for m in metrics], fontsize=8)
    ax.grid(False)
    for i in range(len(metrics)):
        for j in range(len(metrics)):
            value = data[i, j]
            if np.isnan(value):
                continue
            ax.text(
                j,
                i,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=6,
                color="white" if abs(value) > 0.55 else colors()["text_primary"],
            )
    fig.colorbar(mesh, ax=ax, shrink=0.8, label="Spearman ρ")
    ax.set_title("指标间相关性（Spearman）", fontsize=12, loc="left")
    return _to_bytes(fig, fmt)


def scatter_image(
    frame: pd.DataFrame,
    x_metric: str,
    y_metric: str,
    *,
    name_x: str,
    name_y: str,
    unit_x: str = "",
    unit_y: str = "",
    fmt: Format = "png",
) -> bytes:
    _apply_style()
    pair = frame[[x_metric, y_metric]].apply(pd.to_numeric, errors="coerce").dropna()
    fig, ax = plt.subplots(figsize=(5.8, 4.4))
    ax.scatter(
        pair[x_metric],
        pair[y_metric],
        s=18,
        alpha=0.55,
        color=series_colors()[1],
        edgecolor="none",
    )
    ax.set_xlabel(f"{name_x}（{unit_x}）" if unit_x else name_x)
    ax.set_ylabel(f"{name_y}（{unit_y}）" if unit_y else name_y)
    ax.set_title(f"{name_x} 与 {name_y}（n = {len(pair)}）", fontsize=12, loc="left")
    return _to_bytes(fig, fmt)
