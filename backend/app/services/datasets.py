"""数据集服务（SRS FR-01/02/03/14/28/35）。

这里的函数都不碰 HTTP 与数据库事务提交细节以外的状态，方便接口层与导出层复用。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.jsonsafe import sanitize_json
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

#: 上传可用性闸：三个门槛都来自"这份数据还能不能得出结论"，而不是"够不够干净"。
#: 行数下限取 5 而不是 10：连直方图都画不出的数据没有讨论价值（与 captions 的
#: MIN_PLOT_N 一致），而"分组后 n<10 不做检验"已经由 BR-11 单独把关，不必在这里重复拦截。
MIN_ROWS_AFTER_CLEAN = 5
MIN_CORE_RATIO = 0.6
MIN_METRICS_WITH_N = 3

#: 只接受文本表格。特地在语义上区分"扩展名不对"与"其实是二进制/xlsx"，
#: 因为后者的修复动作完全不同（另存为 CSV vs 换个文件）。
ALLOWED_SUFFIXES = {".csv", ".txt"}
BINARY_MAGIC = (b"PK\x03\x04", b"\x89PNG", b"\xff\xd8\xff", b"%PDF", b"GIF8", b"\x1f\x8b")


def _check_upload_payload(filename: str, data: bytes) -> None:
    """文件层闸门：扩展名 / magic bytes / NUL 字节。

    只看扩展名不够（改个名就能过），只看 magic 也不够（.xlsx 与 .zip 同签名，
    错误提示会误导人去解压）。两者都看，且提示语指向"下一步该做什么"。
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix not in ALLOWED_SUFFIXES:
        if suffix in {".xlsx", ".xls"}:
            raise AppError(40003, detail="这是 Excel 文件，请在 Excel 里「另存为 CSV」后再上传")
        raise AppError(40003, detail=f"只接受 CSV 文件（当前后缀 {suffix}）")

    head = data[:8192]
    for magic in BINARY_MAGIC:
        if head.startswith(magic):
            raise AppError(40003, detail="这看起来是二进制文件或压缩包，请上传纯文本 CSV")
    if b"\x00" in head:
        raise AppError(40003, detail="文件里含 NUL 字节，不是纯文本 CSV")


def _purge_artifacts(dataset_id: str, settings: Settings) -> None:
    """删掉这个数据集在磁盘上的一切：原始 CSV 与 S1–S7 的中间产物。

    为什么失败路径也要删：失败的原始文件留在 ``data/raw`` 里既没人会看，
    也不会被任何人清理（``delete_dataset`` 只对列表里能点到的记录生效）。
    反复失败上传会把磁盘喂饱，而界面上看不到是哪些文件占的。
    """
    raw = settings.raw_dir / f"{dataset_id}.csv"
    raw.unlink(missing_ok=True)
    shutil.rmtree(settings.processed_dir / dataset_id, ignore_errors=True)


def _usability_reason(output: PipelineOutput) -> str | None:
    """清洗完再判一次"这份数据能不能撑起结论"（不回滚、不猜测，只给原因）。

    三条门槛的取值理由：
    * 行数 < 5：连直方图都画不出来，任何"分布/检出率"的结论都站不住；
    * 核心字段可解析比例 < 60%：典型情况是表头对上了、值却是"正常/阴性"这类文本，
      清洗会把它们全部置空，S6 于是在**没有任何数据**的情况下输出"全部正常"——
      一份看起来很干净、实际是空壳的报告，比报错危险得多；
    * 有效指标 < 3：只剩一两个指标还能算，热力图与模式判定都失去意义。
    """
    rows = int(output.rows or 0)
    if rows < MIN_ROWS_AFTER_CLEAN:
        return f"清洗后只剩 {rows} 行，至少要 {MIN_ROWS_AFTER_CLEAN} 行才能做分布统计"

    dq = (output.quality or {}).get("dq") or {}
    core = dq.get("DQ-01")
    if core is not None and float(core) < MIN_CORE_RATIO:
        return (
            f"核心字段（hgb / wbc / plt）只有 {float(core) * 100:.0f}% 能解析成数值，"
            f"至少要 {MIN_CORE_RATIO * 100:.0f}%——请确认这些列里装的是数字，而不是'正常/阴性'之类的文字"
        )

    overview = (output.stats or {}).get("overview") or []
    usable = [item for item in overview if int(item.get("n") or 0) >= MIN_ROWS_AFTER_CLEAN]
    if len(usable) < MIN_METRICS_WITH_N:
        return (
            f"只有 {len(usable)} 个指标的有效样本达到 {MIN_ROWS_AFTER_CLEAN} 条，"
            f"至少要 {MIN_METRICS_WITH_N} 个"
        )
    return None


def ensure_usable(dataset: Dataset) -> None:
    """被质量闸拦下的数据集，任何"出结论"的入口都要在这里止步。

    集中成一处，是因为这类判断散落在每个端点里必然漏一个：
    漏掉导出的结果就是"页面上说不可用、文件却照样能下"。
    """
    if dataset.status == "rejected":
        raise AppError(
            42201,
            detail=dataset.error_message or "该数据集未通过质量校验，不能用于分析或导出",
        )


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

    # 文件层闸门：扩展名 + magic bytes（改个后缀就能过扩展名检查，所以两个都看）
    _check_upload_payload(filename, data)

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
        name=(Path(filename or "dataset.csv").stem or "dataset")[:120],
        # Postgres 的 varchar 会真的拒收超长：SQLite 时代没人在意，切 PG 后
        # 一个 300 字符的文件名会让上传 500。截断放在入库前，两套库行为一致。
        original_filename=Path(filename or "dataset.csv").name[:255],
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
        _purge_artifacts(dataset.id, settings)
        raise
    except Exception as exc:  # noqa: BLE001
        dataset.status = "failed"
        dataset.error_message = str(exc)[:500]
        db.commit()
        _purge_artifacts(dataset.id, settings)
        raise AppError(50001, detail=str(exc)[:200]) from exc

    # 可用性闸：清洗之后再判一次"这份数据能不能撑起结论"。
    # 不通过时保留质量报告（用户要能看见为什么被拒），但清掉一切可用于出图的产物，
    # 并把状态置为 rejected —— 之后的统计/图表/导出/报告全部在 ensure_usable 处止步。
    reason = _usability_reason(output)
    if reason is not None:
        dataset.rows = output.rows
        dataset.columns = output.columns
        dataset.mapping = sanitize_json(output.mapping)
        dataset.quality = sanitize_json(output.quality)
        output.clean_report["health"] = output.health
        dataset.clean_report = sanitize_json(output.clean_report)
        dataset.status = "rejected"
        dataset.error_message = reason
        db.commit()
        _purge_artifacts(dataset.id, settings)
        raise AppError(
            42201,
            detail=reason,
            extra={"dataset_id": dataset.id, "status": "rejected"},
        )

    dataset.rows = output.rows
    dataset.columns = output.columns
    dataset.ri_version = output.ri_version
    dataset.ri_source = output.ri_source
    dataset.judged_at = utcnow()
    dataset.ranges_snapshot = sanitize_json(output.ranges_snapshot)
    dataset.unified_ranges = unified_ranges
    dataset.mapping = sanitize_json(output.mapping)
    dataset.quality = sanitize_json(output.quality)
    output.clean_report["health"] = output.health
    # 各阶段耗时一并留档：NFR-P-01/02 的验收要能对着数字说话，而不是"感觉挺快"
    output.clean_report["timings"] = {k: round(v, 3) for k, v in output.timings.items()}
    dataset.clean_report = sanitize_json(output.clean_report)
    dataset.stats = sanitize_json(output.stats)
    dataset.anomaly = sanitize_json(output.anomaly)
    dataset.artifacts = sanitize_json(output.artifacts)
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

    清洗阶段按分组中位数填过的格子，在返回前**重新置空**（BR-21）：填充只服务于
    "行不丢、可筛选"，一旦出现在预览或导出里，用户就会把它当实测值读，而它并不是。
    """
    settings = get_settings()
    ensure_usable(dataset)
    filename = "raw.parquet" if stage == "raw" else "clean.parquet"
    directory = settings.processed_dir / dataset.id
    path = directory / filename
    if not path.exists():
        raise AppError(40401, detail="数据集尚未完成清洗" if stage != "raw" else "数据集原始文件已丢失")
    frame = pd.read_parquet(path)

    mask_path = directory / "imputed.parquet"
    if stage != "raw" and mask_path.exists():
        mask = pd.read_parquet(mask_path)
        n = min(len(frame), len(mask))
        for column in mask.columns:
            if column not in frame.columns:
                continue
            filled = mask[column].to_numpy(dtype=bool)[:n]
            values = frame[column].to_numpy(dtype=object)
            values[:n] = np.where(filled, None, values[:n])
            frame[column] = values
    return frame


def long_frame(dataset: Dataset) -> pd.DataFrame:
    ensure_usable(dataset)
    frames = load_artifacts(dataset.id)
    long = frames.get("flagged")
    if long is None:
        raise AppError(40401, detail="数据集尚无判定结果")
    return long


def summary_frame(dataset: Dataset) -> pd.DataFrame:
    ensure_usable(dataset)
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
