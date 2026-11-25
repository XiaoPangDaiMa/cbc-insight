"""报告与图表导出（SRS FR-20 / FR-21、4.3.4 双通道、8.1）。

两条通道共用同一份计算结果：**报告里的图 = 屏幕上的图**。所以这里不重新统计、不重新
判定，一律走 ``load_artifacts`` 读 S1–S7 落盘的产物，再用 ``render`` 出 PNG/SVG。

导出文件名用 RFC 5987 的 ``filename*`` 传中文（HTTP 头只能是 latin-1，直接塞中文会
``UnicodeEncodeError``）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.config import Settings, get_settings
from app.core.deps import get_current_user, get_owned_dataset
from app.core.errors import AppError
from app.db.models import Dataset, User
from app.pipeline import stats as stats_mod
from app.services import render
from app.services.datasets import ensure_usable
from app.services.loader import load_fields, load_reference_ranges
from app.services.pipeline_runner import load_artifacts
from app.services.report import build_report, save_report

router = APIRouter(prefix="/datasets", tags=["reports"])

IMAGE_KINDS = ("box", "hist", "corr", "scatter")


def _ascii_name(filename: str) -> str:
    """把中文名压成纯 ASCII 兜底名（老浏览器不认 ``filename*``）。

    直接 ``encode("ascii", "ignore")`` 会留下连续下划线和空主干（``blood_count_dataset__2026…html``），
    这里再收敛一次，实在没有可用字符就叫 ``export``。
    """
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned or "export"
    if not re.search(r"[A-Za-z]", cleaned):
        # 全中文名字被压成 "20261119" 这种只剩数字的串，下载下来谁也认不出是什么
        cleaned = f"chart_{cleaned}"
    return f"{cleaned}.{ext}" if ext else cleaned


def _attachment(filename: str, payload: bytes, media_type: str) -> Response:
    """下载响应：ASCII 兜底名 + RFC 5987 中文名。"""
    disposition = f"attachment; filename=\"{_ascii_name(filename)}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


def _bands(metric: str) -> list[dict[str, Any]]:
    _, bands = stats_mod.reference_bands(metric, load_reference_ranges())
    return bands


def _render_chart(dataset: Dataset, kind: str, metric: str | None, fmt: str) -> tuple[bytes, str]:
    """按 kind 出图，返回 (bytes, 建议文件名主干)。"""
    fields = load_fields()
    artifacts = load_artifacts(dataset.id)
    frame = artifacts["clean"]
    long = artifacts["flagged"]

    if kind == "corr":
        correlation = (dataset.stats or {}).get("correlation") or {}
        if not correlation.get("matrix"):
            raise AppError(40401, "该数据集没有可用的相关性矩阵，请先完成分析")
        return render.corr_image(correlation, fmt=fmt), "指标相关性"

    if metric is None:
        metric = "hgb" if "hgb" in fields.metric_fields() else next(iter(long["metric"].unique()), "")
    if not metric or metric not in long["metric"].unique():
        raise AppError(40401, f"指标 {metric} 不在当前数据集中")

    if kind == "scatter":
        correlation = (dataset.stats or {}).get("correlation") or {}
        pair = max(
            (p for p in correlation.get("pairs", []) if p.get("a") == metric or p.get("b") == metric),
            key=lambda p: abs(p.get("rho") or 0),
            default=None,
        )
        if pair is None:
            raise AppError(40401, f"指标 {metric} 没有可用的相关配对")
        x_metric = metric if pair["a"] == metric else pair["b"]
        y_metric = pair["b"] if x_metric == pair["a"] else pair["a"]
        return (
            render.scatter_image(
                frame,
                x_metric,
                y_metric,
                name_x=fields.name_cn(x_metric),
                name_y=fields.name_cn(y_metric),
                unit_x=fields.unit(x_metric),
                unit_y=fields.unit(y_metric),
                fmt=fmt,
            ),
            f"{fields.name_cn(x_metric)}与{fields.name_cn(y_metric)}散点",
        )

    name_cn = fields.name_cn(metric)
    unit = fields.unit(metric)
    decimals = fields.decimals_of(metric)
    bands = _bands(metric)
    if kind == "box":
        return (
            render.box_image(long, metric, name_cn=name_cn, unit=unit, bands=bands, decimals=decimals, fmt=fmt),
            f"{name_cn}箱线图",
        )
    return (
        render.hist_image(long, metric, name_cn=name_cn, unit=unit, bands=bands, decimals=decimals, fmt=fmt),
        f"{name_cn}直方图",
    )


@router.post("/{dataset_id}/report", status_code=status.HTTP_201_CREATED)
def create_report(
    dataset: Dataset = Depends(get_owned_dataset),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """生成单文件 HTML 报告（图片 base64 内嵌），返回下载地址。"""
    ensure_usable(dataset)
    path = save_report(dataset, settings=settings)
    return {
        "report_url": f"/api/v1/datasets/{dataset.id}/report.html",
        "size": path.stat().st_size,
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
    }


@router.get("/{dataset_id}/report.html")
def download_report(
    dataset: Dataset = Depends(get_owned_dataset),
    settings: Settings = Depends(get_settings),
) -> Response:
    """直接返回报告 HTML（不落盘也可用，便于演示时刷新即最新）。"""
    ensure_usable(dataset)
    html_text = build_report(dataset, settings=settings)
    filename = f"{dataset.name}_分析报告_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    return _attachment(filename, html_text.encode("utf-8"), "text/html; charset=utf-8")


@router.get("/{dataset_id}/charts/{kind}/image")
def export_chart_image(
    kind: str,
    metric: str | None = Query(default=None, description="指标编码，如 hgb"),
    fmt: str = Query(default="png", pattern="^(png|svg)$"),
    dataset: Dataset = Depends(get_owned_dataset),
    settings: Settings = Depends(get_settings),
    _: User = Depends(get_current_user),
) -> Response:
    """图表导出（FR-20）：box / hist / corr / scatter，PNG 300 dpi 或 SVG 矢量。"""
    if kind not in IMAGE_KINDS:
        # 参数问题用 42201，不要用 40001（那是"文件编码无法识别"，会给出误导性的修复提示）
        raise AppError(42201, f"不支持的图表类型：{kind}")
    ensure_usable(dataset)
    payload, stem = _render_chart(dataset, kind, metric, fmt)
    media_type = "image/png" if fmt == "png" else "image/svg+xml"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return _attachment(f"{dataset.name}_{stem}_{stamp}.{fmt}", payload, media_type)


__all__ = ["router", "IMAGE_KINDS"]
