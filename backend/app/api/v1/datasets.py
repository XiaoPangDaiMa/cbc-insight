"""数据集接口（SRS 8.1、FR-01~FR-21、FR-28、FR-30~FR-32、FR-35）。

统一约定（本文件内所有端点都遵守，改代码时不要破坏）：

* **越权返回 40401**：见 ``app/core/deps.py``。
* **图表接口一次返回三样**：图 option + 点位 + 一句话结论，不拆成三次请求。
* **导出预览与下载共用** ``build_export_frame``（NFR-M-06、T-29）。
* ``sample_index`` 是清洗后行序、从 0 起，图/表/导出同源。
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.deps import get_current_user, get_owned_dataset
from app.core.errors import AppError
from app.db.models import Dataset, User
from app.db.session import get_db
from app.pipeline.fielddict import FieldDictionary
from app.pipeline.rules import rejudge_metrics
from app.schemas.dataset import (
    ChartRequest,
    ConfirmMappingRequest,
    FilterClause,
    QueryRequest,
    RenameRequest,
)
from app.services import datasets as svc
from app.services import ranges_service
from app.services.chart import box_chart, corr_chart, hist_chart, scatter_chart
from app.services.loader import load_fields
from app.services.pipeline_runner import rejudge as rejudge_pipeline
from app.services.pipeline_runner import run_pipeline

router = APIRouter(prefix="/datasets", tags=["datasets"])

#: 前端图表里出现的 kind（8.1）
CHART_KINDS = ("box", "hist", "corr", "scatter")


# --------------------------------------------------------------------------- 基础信息


def _dataset_payload(dataset: Dataset) -> dict[str, Any]:
    payload = dataset.summary()
    payload["health"] = (dataset.clean_report or {}).get("health", "")
    payload["anomaly_rate"] = (dataset.anomaly or {}).get("anomaly_rate")
    return payload


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_dataset(
    file: UploadFile = File(...),  # noqa: B008
    unified_ranges: bool = Form(False),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    """上传即跑完 S1–S7（9.1），用户只需要看到结果。

    ``unified_ranges=true`` 是上传页的**显式勾选**（FR-16 唯一例外）：数据本身没有
    gender 列时，用户主动声明"按统一区间判定"，否则依赖性别区间的指标一律判 NA（BR-17）。
    """
    data = await file.read()
    eff = ranges_service.effective(db, user)
    dataset = svc.save_upload(
        db,
        user,
        file.filename or "dataset.csv",
        data,
        settings=settings,
        unified_ranges=unified_ranges,
        ranges=eff.ranges,
        ri_source=eff.source,
        ri_kind=eff.kind,
    )
    return {
        "dataset": _dataset_payload(dataset),
        "mapping": dataset.mapping,
        "quality": dataset.quality,
        "clean_report": dataset.clean_report,
        "anomaly": dataset.anomaly,
    }


@router.get("")
def list_datasets(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    from sqlalchemy import func, select

    total = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.user_id == user.id)) or 0
    rows = db.scalars(
        select(Dataset)
        .where(Dataset.user_id == user.id)
        .order_by(Dataset.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {"items": [_dataset_payload(d) for d in rows], "total": int(total), "page": page, "size": size}


@router.get("/{dataset_id}")
def get_dataset(dataset: Dataset = Depends(get_owned_dataset)) -> dict[str, Any]:  # noqa: B008
    return {"dataset": _dataset_payload(dataset)}


@router.patch("/{dataset_id}")
def rename_dataset(
    payload: RenameRequest,
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise AppError(42201, detail="名称不能为空")
    dataset.name = name[:120]
    db.commit()
    return {"ok": True, "dataset": _dataset_payload(dataset)}


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """级联删除：数据库记录 + raw 文件 + processed / rendered 目录（T-18）。"""
    svc.delete_dataset(dataset)
    db.delete(dataset)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- 映射 / 预览 / 质量


@router.get("/{dataset_id}/mapping")
def get_mapping(dataset: Dataset = Depends(get_owned_dataset)) -> dict[str, Any]:  # noqa: B008
    return dataset.mapping or {}


@router.put("/{dataset_id}/mapping")
def confirm_mapping(
    payload: ConfirmMappingRequest,
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    """用户手工确认映射后**重跑整条管线**：不清洗就得不到正确结论，不能只改映射。"""
    raw_path = settings.raw_dir / f"{dataset.id}.csv"
    if not raw_path.exists():
        raise AppError(40401, detail="原始文件已丢失，请重新上传")
    eff = ranges_service.effective(db, user)
    output = run_pipeline(
        raw_path,
        dataset_id=dataset.id,
        settings=settings,
        forced_units=payload.forced_units,
        confirmed_mapping=payload.mapping,
        unified_ranges=bool(dataset.unified_ranges),
        ranges=eff.ranges,
        ri_source=eff.source,
        ri_kind=eff.kind,
    )
    dataset.mapping = output.mapping
    dataset.quality = output.quality
    dataset.clean_report = {**output.clean_report, "health": output.health}
    dataset.stats = output.stats
    dataset.anomaly = output.anomaly
    dataset.artifacts = output.artifacts
    dataset.rows = output.rows
    dataset.columns = output.columns
    dataset.ri_version = output.ri_version
    dataset.ri_source = output.ri_source
    dataset.ranges_snapshot = output.ranges_snapshot
    dataset.judged_at = datetime.now(UTC)
    dataset.status = "cleaned"
    db.commit()
    return {"ok": True, "dataset": _dataset_payload(dataset), "mapping": dataset.mapping}


@router.get("/{dataset_id}/preview")
def preview(
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    stage: str = Query("cleaned", pattern="^(raw|cleaned)$"),
    columns: str | None = Query(None, description="逗号分隔，缺省返回全部列"),
) -> dict[str, Any]:
    frame = svc.stage_frame(dataset, stage)
    if columns:
        wanted = [c.strip() for c in columns.split(",") if c.strip() in frame.columns]
        if wanted:
            frame = frame[wanted]
    total = int(len(frame))
    start = (page - 1) * size
    chunk = frame.iloc[start : start + size]
    return {
        "headers": [str(c) for c in chunk.columns],
        "rows": [[_cell(v) for v in row] for row in chunk.itertuples(index=False)],
        "total": total,
        "page": page,
        "size": size,
        "stage": stage,
        "columns_available": [str(c) for c in svc.stage_frame(dataset, stage).columns],
    }


def _cell(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


@router.post("/{dataset_id}/quality")
def quality(dataset: Dataset = Depends(get_owned_dataset)) -> dict[str, Any]:  # noqa: B008
    return {"issues": (dataset.quality or {}).get("issues", []), "dq_metrics": (dataset.quality or {}).get("dq", {})}


@router.get("/{dataset_id}/clean-report")
def clean_report(dataset: Dataset = Depends(get_owned_dataset)) -> dict[str, Any]:  # noqa: B008
    report = dict(dataset.clean_report or {})
    return {
        "before": report.get("before", {}),
        "after": report.get("after", {}),
        "removed_by_reason": report.get("removed_by_reason", {}),
        "log": report.get("log", []),
        "dropped_columns": report.get("dropped_columns", []),
        "filled": report.get("filled", []),
        "unit_log": report.get("unit_log", []),
        "health": report.get("health", ""),
    }


@router.post("/{dataset_id}/clean")
def run_clean(
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
) -> dict[str, Any]:
    """清洗在**上传时已自动跑完**（9.1）。这个端点只回状态，不重复计算。

    重复计算会让 ``sample_index`` 变一次，用户手里旧图表的点位立刻错位（40402 的来源）。
    """
    if dataset.status != "cleaned":
        raise AppError(42201, detail="该数据集尚未完成清洗，请重新上传")
    report = dataset.clean_report or {}
    return {
        "stage": "cleaned",
        "job_id": None,
        "log_summary": {
            "removed_by_reason": report.get("removed_by_reason", {}),
            "dropped_columns": report.get("dropped_columns", []),
            "health": report.get("health", ""),
        },
    }


# --------------------------------------------------------------------------- 统计 / 图表 / 状态


def _fields() -> FieldDictionary:
    return load_fields()


@router.get("/{dataset_id}/stats")
def stats(
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    group_by: str | None = Query(None, pattern="^(gender|age_band)$"),
) -> dict[str, Any]:
    payload = dict(dataset.stats or {})
    if group_by:
        key = f"by_{group_by}"
        return {"group_by": group_by, "groups": payload.get(key, []), "n": payload.get("n")}
    return payload


@router.post("/{dataset_id}/charts/{kind}")
def chart(
    kind: str,
    payload: ChartRequest,
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    if kind not in CHART_KINDS:
        raise AppError(42201, detail=f"不支持的图表类型 {kind}")
    fields = _fields()

    # 三层区间：临时 > 我的 > 默认（3.5.1）。临时层只在这次请求里活，不落库（FR-37）
    eff = ranges_service.effective(db, user)
    trial = bool(payload.temp_ranges)
    if trial:
        eff = ranges_service.effective(db, user, temp=payload.temp_ranges)
    ranges = eff.ranges

    frame = svc.stage_frame(dataset, payload.stage)
    long = svc.long_frame(dataset)
    if trial and payload.metric:
        # 只重判被拖动的指标：整表重判要 5 s，拖动时期望的是即时反应（NFR-P-12）
        long = rejudge_metrics(
            frame, long, ranges, tuple(payload.temp_ranges or {}), unified=bool(dataset.unified_ranges)
        )
    unit_log = (dataset.clean_report or {}).get("unit_log", [])
    effective_payload = {"source": eff.source, "digest": eff.digest, "trial": trial, "note": eff.note}

    if kind == "corr":
        result = corr_chart(frame, fields, (dataset.stats or {}).get("correlation", {}), settings=settings)
        result["ri_effective"] = effective_payload
        return result

    metric = payload.metric
    if not metric:
        raise AppError(42201, detail="缺少指标参数 metric")
    if metric not in fields.fields:
        raise AppError(42201, detail=f"未知指标 {metric}")

    if kind == "box":
        result = box_chart(frame, long, fields, ranges, metric, settings=settings, unit_log=unit_log)
    elif kind == "hist":
        result = hist_chart(
            frame, long, fields, ranges, metric, settings=settings, bins=payload.bins, unit_log=unit_log
        )
    else:
        y_metric = payload.metric_y or _default_partner(metric)
        result = scatter_chart(frame, fields, metric, y_metric, settings=settings)
    result["ri_effective"] = effective_payload
    return result


def _default_partner(metric: str) -> str:
    """散点图默认配对：优先找有定义性关系的指标（MCH↔HGB、MCHC↔HGB 等）。"""
    partners = {
        "mch": "hgb",
        "mchc": "hgb",
        "hgb": "rbc",
        "rbc": "hgb",
        "hct": "rbc",
        "mcv": "rbc",
        "rdw": "rbc",
    }
    return partners.get(metric, "hgb" if metric != "hgb" else "rbc")


@router.get("/{dataset_id}/metric-status")
def metric_status(dataset: Dataset = Depends(get_owned_dataset)) -> dict[str, Any]:  # noqa: B008
    """FR-30 常驻面板与悬停卡的数据源：每个指标的 n、三态占比、最大偏离度。"""
    fields = _fields()
    overview = (dataset.stats or {}).get("overview", [])
    long = svc.long_frame(dataset)
    items: list[dict[str, Any]] = []
    for row in overview:
        metric = row.get("metric")
        if not metric:
            continue
        spec = fields.spec(str(metric))
        shares = _shares(long, str(metric))
        items.append(
            {
                "metric": metric,
                "name_cn": spec.name_cn if spec else metric,
                "unit": row.get("unit") or (spec.unit if spec else ""),
                "decimals": fields.decimals_of(str(metric)),
                "n": row.get("n"),
                "low": row.get("low"),
                "high": row.get("high"),
                "median": row.get("median"),
                "q1": row.get("q1"),
                "q3": row.get("q3"),
                "min": row.get("min"),
                "max": row.get("max"),
                "max_deviation_pct": row.get("max_deviation_pct"),
                "gender_dependent": row.get("gender_dependent", False),
                "ranges_by_gender": row.get("ranges_by_gender", []),
                "status": _card_status(shares),
                "pct_low": shares["LOW"],
                "pct_normal": shares["NORMAL"],
                "pct_above": shares["HIGH"],
                "pct_na": shares["NA"],
            }
        )
    # 异常项排在正常项之前，且各自按最大偏离度降序（T-21）
    items.sort(key=lambda item: (item["status"] == "NORMAL", -(item["max_deviation_pct"] or 0)))
    return {
        "ri_version": dataset.ri_version,
        "metrics": items,
        "gender_missing_samples": int((dataset.anomaly or {}).get("gender_missing_samples", 0)),
        "anomaly_rate": (dataset.anomaly or {}).get("anomaly_rate"),
    }


def _shares(long: pd.DataFrame, metric: str) -> dict[str, float]:
    subset = long.loc[long["metric"] == metric]
    total = len(subset)
    if not total:
        return {"LOW": 0.0, "NORMAL": 0.0, "HIGH": 0.0, "NA": 0.0}
    return {
        status: round(float((subset["status"] == status).sum() / total), 4)
        for status in ("LOW", "NORMAL", "HIGH", "NA")
    }


def _card_status(shares: dict[str, float]) -> str:
    """卡片状态：两侧都有异常时必须是 MIXED，不能挑一边显示（T-20）。"""
    low, high = shares["LOW"], shares["HIGH"]
    if low > 0 and high > 0:
        return "MIXED"
    if low > 0:
        return "LOW"
    if high > 0:
        return "HIGH"
    if shares["NA"] > 0:
        return "NA"
    return "NORMAL"


@router.get("/{dataset_id}/samples/{sample_index}/profile")
def sample_profile(
    sample_index: int,
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
) -> dict[str, Any]:
    """FR-31 单样本体检单：条长按 ``pos`` 规范化，不按原始值（RK-17）。"""
    long = svc.long_frame(dataset)
    subset = long.loc[long["sample_index"] == sample_index]
    if subset.empty:
        raise AppError(40402, detail="该样本不在当前筛选结果中")
    fields = _fields()
    frame = svc.stage_frame(dataset)
    head = frame.loc[frame["sample_index"] == sample_index]
    items = []
    for row in subset.to_dict("records"):
        spec = fields.spec(str(row.get("metric")))
        items.append(
            {
                "metric": row.get("metric"),
                "name_cn": spec.name_cn if spec else row.get("metric"),
                "unit": spec.unit if spec else "",
                "decimals": fields.decimals_of(str(row.get("metric"))),
                "value": _num(row.get("value")),
                "low": _num(row.get("low")),
                "high": _num(row.get("high")),
                "status": row.get("status"),
                "pos": _num(row.get("pos")),
                "deviation_pct": _num(row.get("deviation_pct")),
                "reason": row.get("reason"),
            }
        )
    gender = head["gender"].iloc[0] if "gender" in head.columns and len(head) else None
    age = head["age"].iloc[0] if "age" in head.columns and len(head) else None
    return {
        "sample_index": sample_index,
        "gender": None if pd.isna(gender) else gender,
        "age": None if pd.isna(age) else float(age),
        "items": items,
        "gender_missing": gender is None or pd.isna(gender),
    }


def _num(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- 区间与重判


@router.get("/{dataset_id}/ranges-snapshot")
def ranges_snapshot(
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """这份数据集的判定用的是哪份区间、现在是否已经"陈旧"（BR-18/BR-20）。

    ``stale=True`` 的含义很具体：**你后来改过我的区间，但这份数据还没按新标准重判**。
    界面必须让人看见这件事，否则"我明明把 HGB 下限改成 120 了，图怎么没变"会变成
    一个只能靠记忆回答的问题（RK-28）。
    """
    # unified 数据集判的是**默认表**（它没有性别信息，也就不该被"我的区间"改写），
    # 所以"当前生效口径"必须按数据集自己的口径算——否则每建一个统一口径数据集，
    # 界面上就会永远亮着一条"陈旧"横幅，而那只是把两种口径混在一起比了个 digest。
    current = ranges_service.default_effective() if dataset.unified_ranges else ranges_service.effective(db, user)
    snapshot = dataset.ranges_snapshot or ranges_service.read_snapshot(dataset.id) or {}
    judged_digest = snapshot.get("digest")
    has_snapshot = bool(snapshot)
    return {
        "dataset_id": dataset.id,
        "ri_version": dataset.ri_version,
        "ri_source": dataset.ri_source,
        "judged_at": dataset.judged_at.isoformat() if dataset.judged_at else None,
        "snapshot": snapshot,
        "has_snapshot": has_snapshot,
        "current": {
            "source": current.source,
            "digest": current.digest,
            "version": current.version,
        },
        # 没有快照 ≠ 不陈旧：那是"判定时没留证据"，界面必须能分开说这两件事（BR-20）
        "stale": bool(has_snapshot and judged_digest and judged_digest != current.digest),
    }


@router.post("/{dataset_id}/rejudge")
def rejudge(
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    """用当前生效的**已保存**区间重放 S6–S7（9.2、BR-19）。

    只重放判定与统计：S1–S5 的产物与 ``sample_index`` 一个字都不动，
    所以用户开着的图表不会因为一次重判集体错位。
    """
    # 统一口径的数据集不参与"我的区间"：它判的是"没有性别信息时的通用值"，
    # 让个人区间覆盖它会把"用户声明"和"个人口径"两件事搅在一起
    eff = ranges_service.default_effective() if dataset.unified_ranges else ranges_service.effective(db, user)
    result = rejudge_pipeline(
        dataset.id,
        eff.ranges,
        ri_source=eff.source,
        ri_kind=eff.kind,
        unified_ranges=bool(dataset.unified_ranges),
        settings=settings,
        fields=_fields(),
    )
    dataset.stats = result["stats"]
    dataset.anomaly = result["anomaly"]
    dataset.ri_version = result["ri_version"]
    dataset.ri_source = result["ri_source"]
    dataset.ranges_snapshot = result["snapshot"]
    dataset.judged_at = datetime.now(UTC)
    db.commit()
    return {
        "ok": True,
        "dataset": _dataset_payload(dataset),
        "changed": result["changed"],
        "timings": result["timings"],
        "ri_source": result["ri_source"],
    }


# --------------------------------------------------------------------------- 筛选 / 异常 / 导出


@router.post("/{dataset_id}/query")
def query(
    payload: QueryRequest,
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
) -> dict[str, Any]:
    frame = svc.stage_frame(dataset, payload.stage)
    frame = svc.apply_filters(frame, payload.filters)
    if payload.gender:
        frame = frame.loc[frame["gender"] == payload.gender]
    if payload.age_min is not None and "age" in frame.columns:
        frame = frame.loc[pd.to_numeric(frame["age"], errors="coerce") >= payload.age_min]
    if payload.age_max is not None and "age" in frame.columns:
        frame = frame.loc[pd.to_numeric(frame["age"], errors="coerce") <= payload.age_max]
    total = int(len(frame))
    start = (payload.page - 1) * payload.size
    chunk = frame.iloc[start : start + payload.size]
    return {
        "rows": [[_cell(v) for v in row] for row in chunk.itertuples(index=False)],
        "headers": [str(c) for c in chunk.columns],
        "total": total,
        "page": payload.page,
        "size": payload.size,
    }


@router.post("/{dataset_id}/anomaly")
def anomaly(
    payload: dict[str, Any] | None = None,
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
) -> dict[str, Any]:
    """异常判定结果在上传时已算好（S6）；这里支持按筛选条件重算统计。"""
    payload = payload or {}
    result = dict(dataset.anomaly or {})
    filters = payload.get("filters") or []
    if filters:
        keep = set(svc.apply_filters(svc.stage_frame(dataset), [FilterClause(**f) for f in filters])["sample_index"])
        summary = svc.summary_frame(dataset)
        subset = summary.loc[summary["sample_index"].isin(keep)]
        abnormal = int((pd.to_numeric(subset.get("n_abnormal"), errors="coerce") > 0).sum())
        result = {
            **result,
            "samples": int(len(subset)),
            "abnormal_samples": abnormal,
            "anomaly_rate": round(abnormal / len(subset), 4) if len(subset) else 0.0,
            "scoped": True,
        }
    result.setdefault("ri_version", dataset.ri_version)
    return result


def _export_headers(kind: str) -> tuple[str, str]:
    if kind not in svc.KIND_LABELS:
        raise AppError(42201, detail=f"未知导出类型 {kind}")
    return kind, svc.KIND_LABELS[kind]


@router.get("/{dataset_id}/export/preview")
def export_preview(
    kind: str,
    scope: str = Query("all", pattern="^(all|filtered)$"),
    stage: str = Query("cleaned", pattern="^(raw|cleaned)$"),
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
) -> dict[str, Any]:
    """预览只读，不造数据：列名/顺序/数量必须与下载完全一致（T-29）。"""
    _export_headers(kind)
    frame, stem = svc.build_export_frame(dataset, kind, stage=stage)
    total = int(len(frame))
    rows = [[_cell(v) for v in row] for row in frame.head(20).itertuples(index=False)]
    return {
        "headers": [str(c) for c in frame.columns],
        "rows": rows,
        "total": total,
        "filename": f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        "scope": scope,
    }


@router.get("/{dataset_id}/export/{kind}")
def export(
    kind: str,
    scope: str = Query("all", pattern="^(all|filtered)$"),
    stage: str = Query("cleaned", pattern="^(raw|cleaned)$"),
    dataset: Dataset = Depends(get_owned_dataset),  # noqa: B008
) -> Response:
    """导出 CSV：UTF-8 with BOM、``\\r\\n``、``index=False``（NFR-C-03、8.2）。

    同名 meta 以响应头 ``X-Export-Meta`` 携带（单文件下载无法同时给两个附件，
    但预览端与前端"最近一次导出"记录需要这份元信息，否则无从复现）。
    """
    _export_headers(kind)
    frame, stem = svc.build_export_frame(dataset, kind, stage=stage)
    if frame.empty:
        raise AppError(42201, detail="当前条件下没有任何记录，未生成文件")
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\r\n")
    content = ("\ufeff" + buffer.getvalue()).encode("utf-8")
    filename = f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    meta = {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "kind": kind,
        "scope": scope,
        "stage": stage,
        "rows": int(len(frame)),
        "columns": [str(c) for c in frame.columns],
        "ri_version": dataset.ri_version,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    # HTTP 头只能是 latin-1：中文文件名走 RFC 5987 的 filename*，中文元信息走 ASCII 转义 JSON
    ascii_name = f"{dataset.id[:8]}_{kind}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "X-Export-Meta": json.dumps(meta, ensure_ascii=True),
            "X-Export-Filename": quote(filename),
        },
    )
