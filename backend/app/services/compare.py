"""多数据集并排对比（FR-29）。

这个模块的存在理由是"能看见差异"，**不是**"证明差异"。所以它只有三件事：

1. 每份数据集的描述统计（n / 均值 / 标准差 / 中位数 / 四分位 / 极值）；
2. 每份数据集自己口径下的三态占比（偏低 / 正常 / 偏高 / 未判定）；
3. 缺哪个指标、为什么缺（进 ``excluded``），而不是补 0 让表格看起来整齐。

**它不做的事**（BR-13，写在这里是为了让后来改代码的人看见）：
不做任何组间检验、不给 p 值、不出现"显著/差异明显"这类措辞。两份公开数据集
来自不同人群、不同仪器、不同参考区间，把它们当作两个"组"做检验，在方法上就是错的，
而错误的结论一旦进了报告，比没有结论更糟。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Dataset, User
from app.pipeline.fielddict import FieldDictionary
from app.services.datasets import long_frame, stage_frame
from app.services.loader import load_fields

MAX_DATASETS = 4
MIN_DATASETS = 2

DISCLAIMER = (
    "仅并排展示：两份数据的样本来源、采集时间与参考区间都可能不同，"
    "因此不做任何统计检验，也不比较 p 值；两列数字的差别不能解读为"
    "「某人群确实更高/更低」。"
)


@dataclass(slots=True)
class MetricCell:
    dataset_id: str
    n: int
    missing: int
    mean: float | None
    sd: float | None
    median: float | None
    q1: float | None
    q3: float | None
    minimum: float | None
    maximum: float | None
    pct_low: float | None
    pct_normal: float | None
    pct_above: float | None
    pct_na: float | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "n": self.n,
            "missing": self.missing,
            "mean": self.mean,
            "sd": self.sd,
            "median": self.median,
            "q1": self.q1,
            "q3": self.q3,
            "min": self.minimum,
            "max": self.maximum,
            "pct_low": self.pct_low,
            "pct_normal": self.pct_normal,
            "pct_above": self.pct_above,
            "pct_na": self.pct_na,
        }


@dataclass(slots=True)
class DatasetBlock:
    dataset: Dataset
    frame: pd.DataFrame
    long: pd.DataFrame
    cells: dict[str, MetricCell] = field(default_factory=dict)
    missing_metrics: dict[str, str] = field(default_factory=dict)

    @property
    def dataset_id(self) -> str:
        return str(self.dataset.id)


def _round(value: float | None, decimals: int = 4) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), decimals)


def _status_shares(long: pd.DataFrame, metric: str) -> dict[str, float | None]:
    """按长表里"当时这条样本实际被判成什么"统计占比。

    刻意不重新判一次：对比页要展示的是**各数据集自己的判定结果**，重算会让
    "我的区间"与"统一口径"两种数据集的占比都变成默认口径，反而掩盖了差异。
    """
    rows = long[long["metric"] == metric]
    total = len(rows)
    if total == 0:
        return {"pct_low": None, "pct_normal": None, "pct_above": None, "pct_na": None}
    counts = rows["status"].astype(str).str.upper().value_counts()
    normal = int(counts.get("NORMAL", 0))
    low = int(counts.get("LOW", 0))
    high = int(counts.get("HIGH", 0))
    return {
        "pct_low": _round(low / total),
        "pct_normal": _round(normal / total),
        "pct_above": _round(high / total),
        # MIXED 也落在"未判定"里：一个指标两侧都越界时，说它"偏高"或"偏低"都是错的
        "pct_na": _round((total - low - normal - high) / total),
    }


def _cell(block: DatasetBlock, metric: str) -> MetricCell | None:
    if metric not in block.frame.columns:
        return None
    series = pd.to_numeric(block.frame[metric], errors="coerce").dropna()
    total_rows = len(block.frame)
    if series.empty:
        return None
    shares = _status_shares(block.long, metric)
    return MetricCell(
        dataset_id=block.dataset_id,
        n=int(series.size),
        missing=int(total_rows - series.size),
        mean=_round(series.mean(), 3),
        sd=_round(series.std(ddof=1), 3) if series.size > 1 else None,
        median=_round(series.median(), 3),
        q1=_round(series.quantile(0.25), 3),
        q3=_round(series.quantile(0.75), 3),
        minimum=_round(series.min(), 3),
        maximum=_round(series.max(), 3),
        pct_low=shares["pct_low"],
        pct_normal=shares["pct_normal"],
        pct_above=shares["pct_above"],
        pct_na=shares["pct_na"],
    )


def _load_block(dataset: Dataset) -> DatasetBlock:
    frame = stage_frame(dataset, "cleaned")
    long = long_frame(dataset)
    return DatasetBlock(dataset=dataset, frame=frame, long=long)


def _metric_order(fields: FieldDictionary, wanted: Sequence[str] | None) -> list[str]:
    known = fields.metric_fields()
    if wanted:
        unknown = [m for m in wanted if m not in known]
        if unknown:
            raise AppError(42201, f"不认识的指标：{'、'.join(unknown)}")
        return list(dict.fromkeys(wanted))
    return list(known)


def compare_stats(
    db: Session,
    user: User,
    dataset_ids: Iterable[str],
    metrics: Sequence[str] | None = None,
    *,
    fields: FieldDictionary | None = None,
) -> dict[str, Any]:
    ids = list(dict.fromkeys(dataset_ids))
    if len(ids) < MIN_DATASETS:
        raise AppError(42201, f"并排对比至少需要 {MIN_DATASETS} 个数据集")
    if len(ids) > MAX_DATASETS:
        raise AppError(42201, f"并排对比最多 {MAX_DATASETS} 个数据集（再多就没人看了，也打印不下）")

    fields = fields or load_fields()
    found = {
        str(row.id): row
        for row in db.scalars(select(Dataset).where(Dataset.user_id == user.id, Dataset.id.in_(ids)))
    }
    # 别人的/不存在的都走 40401，避免用 id 试探别人有哪些数据集（与 deps.get_owned_dataset 同口径）
    missing = [dataset_id for dataset_id in ids if dataset_id not in found]
    if missing:
        raise AppError(40401, f"数据集不存在：{'、'.join(missing)}")

    ordered = [found[dataset_id] for dataset_id in ids]
    blocks = [_load_block(dataset) for dataset in ordered]
    metric_list = _metric_order(fields, metrics)

    side_by_side: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for metric in metric_list:
        cells: list[dict[str, Any]] = []
        absent: list[dict[str, Any]] = []
        for block in blocks:
            cell = _cell(block, metric)
            if cell is None:
                reason = "该数据集没有这一列" if metric not in block.frame.columns else "该列全部为空"
                absent.append(
                    {
                        "dataset_id": block.dataset_id,
                        "dataset_name": block.dataset.name,
                        "metric": metric,
                        "reason": reason,
                    }
                )
                continue
            cells.append(cell.to_payload())
        # 一份数据集都没有这一列时，它不是"被排除的对比项"，而是"这两份数据都没有这个指标"，
        # 列进 excluded 只会制造十几条噪音（15 个指标 × 2 份数据几乎全是这种）。
        if not cells:
            continue
        excluded.extend(absent)
        if len(cells) < 2:
            continue
        side_by_side.append(
            {
                "metric": metric,
                "name_cn": fields.name_cn(metric),
                "unit": fields.unit(metric),
                "decimals": fields.decimals_of(metric),
                "cells": cells,
            }
        )

    datasets_payload = [
        {
            "dataset_id": block.dataset_id,
            "name": block.dataset.name,
            "rows": int(len(block.frame)),
            "ri_version": block.dataset.ri_version,
            "ri_source": block.dataset.ri_source,
            "unified_ranges": bool(block.dataset.unified_ranges),
            "judged_at": block.dataset.judged_at.isoformat() if block.dataset.judged_at else None,
        }
        for block in blocks
    ]

    notes: list[str] = []
    versions = {item["ri_version"] for item in datasets_payload}
    sources = {item["ri_source"] for item in datasets_payload}
    if len(versions) > 1:
        notes.append(
            "各数据集使用了不同的参考区间版本（"
            + "、".join(sorted(str(v) for v in versions))
            + "），三态占比不可直接横向比较。"
        )
    if len(sources) > 1:
        notes.append("各数据集的判定口径不同（" + "、".join(sorted(str(s) for s in sources)) + "），判定结果分别成立。")
    if any(item["unified_ranges"] for item in datasets_payload):
        notes.append("标记为「统一口径」的数据集未按性别分组判定，其偏低/偏高占比与按性别判定的数据集不是同一把尺子。")
    if not notes:
        notes.append("各数据集使用相同的参考区间版本与判定口径，三态占比可以横向对照。")

    return {
        "datasets": datasets_payload,
        "metrics": [item["metric"] for item in side_by_side],
        "side_by_side": side_by_side,
        "excluded": excluded,
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }
