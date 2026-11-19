"""数据集服务（SRS FR-01/02/03/14/28/35）。

这里的函数都不碰 HTTP 与数据库事务提交细节以外的状态，方便接口层与导出层复用。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import Dataset, User, utcnow
from app.pipeline.reference import ReferenceRanges
from app.schemas.dataset import FilterClause
from app.services.pipeline_runner import PipelineOutput, load_artifacts, run_pipeline

KIND_LABELS: dict[str, str] = {
    "items": "逐指标判定",
    "summary": "样本级汇总",
    "stats": "描述统计",
    "filtered": "筛选结果",
}


def save_upload(
    db: Session,
    user: User,
    filename: str,
    data: bytes,
    *,
    settings: Settings | None = None,
    unified_ranges: bool = False,
    ranges: ReferenceRanges | None = None,
    ri_source: str = "default",
    ri_kind: str = "default",
) -> Dataset:
    """落盘 → 哈希判重 → 自动跑 S1–S7（9.1：上传即自动串联）。

    ``unified_ranges`` 由上传页的显式勾选传入（FR-16 唯一例外）：仅当用户声明
    "本数据集无性别，按统一区间判定"时才为 True；默认 False 保持 BR-17 的 NA 语义。

    ``ranges`` 是**当次生效的三层区间**（临时 > 我的 > 默认，3.5.1）。不传则用默认表——
    上传时就用用户自己的区间，才不会出现"页面显示我的区间、结果却按默认表判"的错位。
    """
    settings = settings or get_settings()
    settings.ensure_dirs()

    if len(data) > settings.max_upload_bytes:
        raise AppError(41301, detail=f"当前 {len(data) / 1024 / 1024:.1f} MB")
    if not data.strip():
        raise AppError(40003, detail="文件为空")

    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Dataset).where(Dataset.user_id == user.id, Dataset.sha256 == digest))
    if existing is not None:
        raise AppError(40901, extra={"dataset_id": existing.id, "name": existing.name})

    count = len(
        db.scalars(select(Dataset.id).where(Dataset.user_id == user.id)).all()
    )
    if count >= settings.max_datasets_per_user:
        raise AppError(40002, detail=f"单用户最多 {settings.max_datasets_per_user} 个数据集")

    dataset = Dataset(
        user_id=user.id,
        name=Path(filename or "dataset.csv").stem[:120] or "dataset",
        original_filename=Path(filename or "dataset.csv").name,
        sha256=digest,
        status="uploaded",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    raw_path = settings.raw_dir / f"{dataset.id}.csv"
    raw_path.write_bytes(data)

    try:
        output: PipelineOutput = run_pipeline(
            raw_path,
            dataset_id=dataset.id,
            settings=settings,
            unified_ranges=unified_ranges,
            ranges=ranges,
            ri_source=ri_source,
            ri_kind=ri_kind,
        )
    except AppError:
        dataset.status = "failed"
        dataset.error_message = "管线执行失败"
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        dataset.status = "failed"
        dataset.error_message = str(exc)[:500]
        db.commit()
        raise AppError(50001, detail=str(exc)[:200]) from exc

    dataset.rows = output.rows
    dataset.columns = output.columns
    dataset.ri_version = output.ri_version
    dataset.ri_source = output.ri_source
    dataset.judged_at = utcnow()
    dataset.ranges_snapshot = output.ranges_snapshot
    dataset.unified_ranges = unified_ranges
    dataset.mapping = output.mapping
    dataset.quality = output.quality
    output.clean_report["health"] = output.health
    # 各阶段耗时一并留档：NFR-P-01/02 的验收要能对着数字说话，而不是"感觉挺快"
    output.clean_report["timings"] = {k: round(v, 3) for k, v in output.timings.items()}
    dataset.clean_report = output.clean_report
    dataset.stats = output.stats
    dataset.anomaly = output.anomaly
    dataset.artifacts = output.artifacts
    dataset.status = "cleaned"
    db.commit()
    db.refresh(dataset)
    return dataset


def delete_dataset(dataset: Dataset, *, settings: Settings | None = None) -> None:
    """级联删文件：raw 单文件 + 该数据集的 processed 目录（FR-28、T-18）。"""
    settings = settings or get_settings()
    raw_path = settings.raw_dir / f"{dataset.id}.csv"
    if raw_path.exists():
        raw_path.unlink()
    work_dir = settings.processed_dir / dataset.id
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    rendered = settings.rendered_dir / dataset.id
    if rendered.exists():
        shutil.rmtree(rendered, ignore_errors=True)


def apply_filters(frame: pd.DataFrame, filters: list[FilterClause] | None) -> pd.DataFrame:
    """把 8.1/query 的过滤条件翻译成布尔掩码（FR-14）。

    只对存在的列生效——筛选条件里出现表里没有的指标时忽略它，而不是抛错，
    因为用户可能刚切换了数据集而前端还带着上一份的筛选条件（RK-11 的同类风险）。
    """
    if not filters:
        return frame
    result = frame
    for clause in filters:
        if clause.metric not in result.columns:
            continue
        series = pd.to_numeric(result[clause.metric], errors="coerce")
        value = clause.value
        if clause.op == "lt":
            mask = series < value
        elif clause.op == "lte":
            mask = series <= value
        elif clause.op == "gt":
            mask = series > value
        elif clause.op == "eq":
            mask = series == value
        elif clause.op == "between":
            mask = series.between(value, clause.upper, inclusive="both")
        else:
            mask = series >= value
        result = result.loc[mask.fillna(False)]
    return result


def select_frame(
    dataset: Dataset,
    *,
    stage: str = "cleaned",
    filters: list[FilterClause] | None = None,
    gender: str | None = None,
    age_min: float | None = None,
    age_max: float | None = None,
) -> pd.DataFrame:
    """把「阶段 + 指标条件 + 性别 + 年龄」合成一张表（FR-14）。

    **筛选、预览、导出必须走同一段逻辑**：如果这里和 ``/query`` 各写一份，
    用户看到的行数与导出的行数迟早会对不上，而且两边看起来都"合理"（RK-19 的同类风险）。
    """
    frame = stage_frame(dataset, stage)
    frame = apply_filters(frame, filters)

    if gender:
        if "gender" not in frame.columns:
            return frame.iloc[0:0]
        frame = frame.loc[frame["gender"].astype("string").str.lower() == gender.lower()]

    if "age" in frame.columns and (age_min is not None or age_max is not None):
        ages = pd.to_numeric(frame["age"], errors="coerce")
        if age_min is not None:
            frame = frame.loc[ages >= age_min]
            ages = ages.loc[frame.index]
        if age_max is not None:
            frame = frame.loc[ages <= age_max]
    return frame


def stage_frame(dataset: Dataset, stage: str = "cleaned") -> pd.DataFrame:
    """取某一阶段的宽表（图表与导出共用，保证同源）。

    ``stage=raw`` 读的是 S1 的原始列名版本，用于"清洗前后对比"（FR-06）；
    ``stage=cleaned`` 才是后面所有统计、图表、判定的口径。
    """
    settings = get_settings()
    filename = "raw.parquet" if stage == "raw" else "clean.parquet"
    path = settings.processed_dir / dataset.id / filename
    if not path.exists():
        raise AppError(40401, detail="数据集尚未完成清洗" if stage != "raw" else "数据集原始文件已丢失")
    return pd.read_parquet(path)


def long_frame(dataset: Dataset) -> pd.DataFrame:
    frames = load_artifacts(dataset.id)
    long = frames.get("flagged")
    if long is None:
        raise AppError(40401, detail="数据集尚无判定结果")
    return long


def summary_frame(dataset: Dataset) -> pd.DataFrame:
    frames = load_artifacts(dataset.id)
    summary = frames.get("summary")
    if summary is None:
        raise AppError(40401, detail="数据集尚无判定结果")
    return summary


def build_export_frame(
    dataset: Dataset,
    kind: str,
    *,
    stage: str = "cleaned",
    filters: list[FilterClause] | None = None,
    gender: str | None = None,
    age_min: float | None = None,
    age_max: float | None = None,
    only_abnormal: bool = False,
) -> tuple[pd.DataFrame, str]:
    """**导出预览与下载共用这一个函数**（NFR-M-06、RK-19、T-29）。

    返回 (表, 文件名主干)。列名、顺序、数量只能在这里定义一次，否则预览与下载迟早不一致。
    """
    if kind not in KIND_LABELS:
        raise AppError(42201, detail=f"未知导出类型 {kind}")

    scope = {"gender": gender, "age_min": age_min, "age_max": age_max}
    if kind == "items":
        long = long_frame(dataset)
        keep = set(select_frame(dataset, stage=stage, filters=filters, **scope)["sample_index"])
        frame = long.loc[long["sample_index"].isin(keep)].copy()
    elif kind == "summary":
        frame = summary_frame(dataset).copy()
        # 排序即"异常清单"的默认顺序：异常项多的在前，同样多时偏离大的在前（FR-18）
        if {"n_abnormal", "severity"} <= set(frame.columns):
            frame = frame.sort_values(["n_abnormal", "severity"], ascending=[False, False], kind="stable")
        if only_abnormal and "n_abnormal" in frame.columns:
            frame = frame.loc[pd.to_numeric(frame["n_abnormal"], errors="coerce").fillna(0) > 0]
        keep = set(select_frame(dataset, stage=stage, filters=filters, **scope)["sample_index"])
        frame = frame.loc[frame["sample_index"].isin(keep)]
    elif kind == "filtered":
        frame = select_frame(dataset, stage=stage, filters=filters, **scope).copy()
    else:  # stats
        frame = pd.DataFrame(dataset.stats.get("overview") or [])

    frame = frame.rename(columns=COLUMN_LABELS)
    slug = dataset.name.replace(" ", "_")[:40] or "dataset"
    return frame, f"{slug}_{kind}"


#: 导出列的中文表头（预览与下载同源，T-29）
COLUMN_LABELS: dict[str, str] = {
    "sample_index": "样本序号",
    "gender": "性别",
    "age": "年龄",
    "age_band": "年龄段",
    "metric": "指标",
    "name_cn": "指标名称",
    "unit": "单位",
    "value": "实测值",
    "low": "参考下限",
    "high": "参考上限",
    "status": "判定",
    "deviation_pct": "偏离度(%)",
    "pos": "区间位置",
    "reason": "未判定原因",
    "pattern": "模式",
    "patterns": "命中模式",
    "severity": "严重度",
    "n_abnormal": "异常指标数",
    "abnormal_metrics": "异常指标",
    "na_metrics": "未判定指标",
    "gender_missing": "性别缺失",
    "ri_unified": "统一口径判定",
    "n": "样本数",
    "missing": "缺失数",
    "mean": "均值",
    "std": "标准差",
    "median": "中位数",
    "q1": "Q1",
    "q3": "Q3",
    "min": "最小值",
    "max": "最大值",
    "max_deviation_pct": "最大偏离度(%)",
    "pct_low": "偏低占比",
    "pct_normal": "正常占比",
    "pct_above": "偏高占比",
    "pct_na": "未判定占比",
    "decimals": "小数位",
}
