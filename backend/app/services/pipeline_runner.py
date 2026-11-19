"""S1–S7 串联执行，并把这七步的产物落盘（SRS 9、9.1、FR-05/06/07）。

为什么每步都要落盘：答辩时"这一步为什么少了两行"必须能当场回答。任何一步出问题
都能单独重跑，也让报告可以按当时的 ``ri_version`` 复现（7.3 决策 7）。

产物目录：``data/processed/{dataset_id}/``
``raw.parquet`` / ``mapped.parquet`` / ``clean.parquet`` / ``flagged.parquet``
``summary.parquet`` / ``quality.json`` / ``clean_report.json`` / ``stats.json`` / ``anomaly.json``
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.core.config import Settings, get_settings
from app.core.errors import AppError, MissingFieldsError, UnitAmbiguousError
from app.pipeline.captions import caption_health
from app.pipeline.cleaning import CleanResult, clean
from app.pipeline.derive import add_sample_index
from app.pipeline.fielddict import FieldDictionary, MappingConfig
from app.pipeline.mapping import FieldMapper, MappingResult
from app.pipeline.reading import read_csv
from app.pipeline.reference import ReferenceRanges
from app.pipeline.rules import anomaly_summary, flag_frame
from app.pipeline.stats import compare_groups, correlation, group_overview, metric_overview
from app.pipeline.units import UnitDecision, apply_decisions, detect_all
from app.pipeline.validators import validate
from app.services import ranges_service
from app.services.loader import (
    load_fields,
    load_mapping_config,
    load_reference_ranges,
)


@dataclass
class PipelineOutput:
    mapping: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    clean_report: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    anomaly: dict = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    rows: int = 0
    columns: int = 0
    ri_version: str = ""
    ri_source: str = "default"
    ranges_snapshot: dict = field(default_factory=dict)
    unified_ranges: bool = False
    health: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    #: 供图表服务复用，不落库
    clean_frame: pd.DataFrame | None = None
    long: pd.DataFrame | None = None
    summary: pd.DataFrame | None = None

    def to_record(self) -> dict:
        return {
            "mapping": self.mapping,
            "quality": self.quality,
            "clean_report": self.clean_report,
            "stats": self.stats,
            "anomaly": self.anomaly,
            "artifacts": self.artifacts,
            "rows": self.rows,
            "columns": self.columns,
            "ri_version": self.ri_version,
            "ri_source": self.ri_source,
            "ranges_snapshot": self.ranges_snapshot,
            "unified_ranges": self.unified_ranges,
            "health": self.health,
            "timings": {k: round(v, 3) for k, v in self.timings.items()},
        }


def _write_json(data: dict, path: Path) -> None:
    import json

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(
    csv_path: Path,
    *,
    dataset_id: str,
    settings: Settings | None = None,
    fields: FieldDictionary | None = None,
    config: MappingConfig | None = None,
    ranges: ReferenceRanges | None = None,
    forced_units: dict[str, str] | None = None,
    confirmed_mapping: dict[str, str] | None = None,
    unified_ranges: bool = False,
    ri_source: str = "default",
    ri_kind: str = "default",
) -> PipelineOutput:
    """读取 → 映射 → 单位归一 → 校验 → 清洗 → 派生 → 判定 → 统计。

    参数全部可注入，是为了让单元测试不必读全局配置就能跑同一套代码。

    ``unified_ranges=True`` 只在数据集没有 gender 列、且用户在上传页显式勾选了
    "按统一区间判定"时传 True（FR-16 的唯一例外）；其余情况保持 BR-17 的 NA 语义。
    """
    settings = settings or get_settings()
    fields = fields or load_fields()
    config = config or load_mapping_config()
    ranges = ranges or load_reference_ranges()

    out = PipelineOutput()
    timings = out.timings
    work_dir = settings.processed_dir / dataset_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # --- S1 读取 ---
    started = time.perf_counter()
    reading = read_csv(csv_path)
    frame = reading.frame
    _write_parquet(frame, work_dir / "raw.parquet", out, "raw")
    timings["S1_read"] = time.perf_counter() - started

    # --- S2 映射 + 单位归一 ---
    started = time.perf_counter()
    mapper = FieldMapper(fields, config)
    result: MappingResult = mapper.suggest(reading.frame)
    if confirmed_mapping:
        # 用户手工确认过的映射优先（FR-02）
        result.mapping = {src: tgt for src, tgt in confirmed_mapping.items() if tgt}
    if result.missing_required:
        raise MissingFieldsError(result.missing_required)

    mapped = frame.rename(columns=result.mapping)
    mapped = mapped.loc[:, [c for c in mapped.columns if c in fields.fields or c in ("gender", "age")]]
    mapped = mapped.copy()

    decisions = detect_all(mapped, tuple(fields.metric_fields()), forced=forced_units)
    ambiguous = [d for d in decisions if d.ambiguous]
    if ambiguous:
        first = ambiguous[0]
        raise UnitAmbiguousError(first.metric, float(first.median or 0), list(first.candidates))
    mapped, unit_log = apply_decisions(mapped, decisions)

    out.mapping = result.to_payload()
    if unit_log:
        out.mapping["unit_log"] = unit_log
    _write_parquet(mapped, work_dir / "mapped.parquet", out, "mapped")
    timings["S2_mapping"] = time.perf_counter() - started

    # --- S3 校验（不改数据）---
    started = time.perf_counter()
    validated, report = validate(mapped, fields, unit_decisions=decisions)
    out.quality = report.to_payload()
    _write_json(out.quality, work_dir / "quality.json")
    out.artifacts["quality"] = str(work_dir / "quality.json")
    timings["S3_validate"] = time.perf_counter() - started

    # --- S4 清洗 ---
    started = time.perf_counter()
    cleaned: CleanResult = clean(mapped, validated, fields, config)
    out.clean_report = cleaned.to_payload()
    out.clean_report["unit_log"] = unit_log
    _write_json(out.clean_report, work_dir / "clean_report.json")
    out.artifacts["clean_report"] = str(work_dir / "clean_report.json")
    timings["S4_clean"] = time.perf_counter() - started

    # --- S5 派生（sample_index 必须是清洗后的行序，图/表/导出同源）---
    clean_frame = add_sample_index(cleaned.frame)
    _write_parquet(clean_frame, work_dir / "clean.parquet", out, "clean")

    # --- S6 判定 ---
    started = time.perf_counter()
    long, summary = flag_frame(clean_frame, ranges, unified=unified_ranges)
    out.ri_version = ranges.version
    out.ri_source = f"unified@{ranges.version}" if unified_ranges else ri_source
    out.unified_ranges = unified_ranges
    out.anomaly = anomaly_summary(long, summary)
    out.anomaly["ri_version"] = ranges.version
    out.anomaly["ri_source"] = out.ri_source
    # 判定即快照（3.5.1）：这一刻用的是哪份表，之后谁改了区间都不影响这份结论
    out.ranges_snapshot = ranges_service.snapshot_for(
        dataset_id,
        ranges,
        source=ri_source,
        kind=ri_kind,
        unified=unified_ranges,
        settings=settings,
    )
    out.artifacts["ranges_snapshot"] = str(ranges_service.snapshot_path(dataset_id, settings))
    _write_parquet(long, work_dir / "flagged.parquet", out, "flagged")
    _write_parquet(summary, work_dir / "summary.parquet", out, "summary")
    _write_json(out.anomaly, work_dir / "anomaly.json")
    out.artifacts["anomaly"] = str(work_dir / "anomaly.json")
    timings["S6_flag"] = time.perf_counter() - started

    # --- S7 统计 ---
    started = time.perf_counter()
    out.stats = _stats_payload(
        clean_frame,
        long,
        fields,
        ranges=ranges,
        unified=unified_ranges,
        ri_source=out.ri_source,
        gender_missing_samples=int(out.anomaly.get("gender_missing_samples", 0)),
    )
    _write_json(out.stats, work_dir / "stats.json")
    out.artifacts["stats"] = str(work_dir / "stats.json")
    timings["S7_stats"] = time.perf_counter() - started

    # --- 数据健康度摘要（4.2.0 约定 2 的那一句话）---
    out.health = _health_line(cleaned, unit_log)

    out.rows = int(len(clean_frame))
    out.columns = int(len(clean_frame.columns))
    out.clean_frame = clean_frame
    out.long = long
    out.summary = summary
    return out


def _write_parquet(frame: pd.DataFrame, path: Path, out: PipelineOutput, key: str) -> None:
    frame.to_parquet(path, index=False)
    out.artifacts[key] = str(path)


def _stats_payload(
    clean_frame: pd.DataFrame,
    long: pd.DataFrame,
    fields: FieldDictionary,
    *,
    ranges: ReferenceRanges,
    unified: bool,
    ri_source: str,
    gender_missing_samples: int,
) -> dict:
    """S7 的统计装配。抽成函数是因为**重判也要产出同一份结构**（9.2）。"""
    return {
        "n": int(len(clean_frame)),
        "ri_version": ranges.version,
        "ri_source": ri_source,
        "overview": metric_overview(clean_frame, long, fields, ranges=ranges, unified=unified),
        "by_gender": group_overview(clean_frame, long, fields, by="gender"),
        "by_age_band": group_overview(clean_frame, long, fields, by="age_band"),
        "comparisons": {
            str(metric): compare_groups(clean_frame, str(metric)) for metric in fields.metric_fields()
        },
        "correlation": correlation(clean_frame, fields),
        "gender_missing_samples": int(gender_missing_samples),
    }


def rejudge(
    dataset_id: str,
    ranges: ReferenceRanges,
    *,
    ri_source: str,
    ri_kind: str = "user",
    unified_ranges: bool = False,
    settings: Settings | None = None,
    fields: FieldDictionary | None = None,
) -> dict:
    """**只重放 S6–S7**，不动 S1–S5（9.2）。

    为什么不能整条管线重跑：S4 会重新清洗、重新编号 ``sample_index``，用户手里打开的
    图表与体检单立刻错位，界面上看不出问题但所有点位都指向别人（RK-28 的近亲）。
    ``clean.parquet`` 是已经定型的中间结果，重判只读它。

    返回新统计、新异常摘要、新快照与"变了多少"——只有最后这一项能让用户判断
    "这次改标准，是谁从正常变成了偏低"。
    """
    settings = settings or get_settings()
    fields = fields or load_fields()
    work_dir = settings.processed_dir / dataset_id
    clean_path = work_dir / "clean.parquet"
    if not clean_path.exists():
        raise AppError(40401, detail="该数据集尚未清洗完成，无法重判")
    clean_frame = pd.read_parquet(clean_path)

    old_long: pd.DataFrame | None = None
    old_flag = work_dir / "flagged.parquet"
    if old_flag.exists():
        old_long = pd.read_parquet(old_flag)

    timings: dict[str, float] = {}
    started = time.perf_counter()
    long, summary = flag_frame(clean_frame, ranges, unified=unified_ranges)
    timings["S6_flag"] = time.perf_counter() - started

    anomaly = anomaly_summary(long, summary)
    anomaly["ri_version"] = ranges.version
    anomaly["ri_source"] = f"unified@{ranges.version}" if unified_ranges else ri_source

    started = time.perf_counter()
    stats = _stats_payload(
        clean_frame,
        long,
        fields,
        ranges=ranges,
        unified=unified_ranges,
        ri_source=anomaly["ri_source"],
        gender_missing_samples=int(anomaly.get("gender_missing_samples", 0)),
    )
    timings["S7_stats"] = time.perf_counter() - started

    snapshot = ranges_service.snapshot_for(
        dataset_id,
        ranges,
        source=ri_source,
        kind=ri_kind,
        unified=unified_ranges,
        settings=settings,
    )

    # 落盘顺序：先写新产物再返回，接口拿到 200 时磁盘已经是最新的
    long.to_parquet(work_dir / "flagged.parquet", index=False)
    summary.to_parquet(work_dir / "summary.parquet", index=False)
    _write_json(anomaly, work_dir / "anomaly.json")
    _write_json(stats, work_dir / "stats.json")

    changed = _diff_verdicts(old_long, long)
    return {
        "stats": stats,
        "anomaly": anomaly,
        "snapshot": snapshot,
        "ri_version": ranges.version,
        "ri_source": anomaly["ri_source"],
        "timings": {k: round(v, 3) for k, v in timings.items()},
        "changed": changed,
    }


def _diff_verdicts(old_long: pd.DataFrame | None, new_long: pd.DataFrame) -> dict[str, int]:
    """比较两次判定的三态变化：多少"样本×指标"、多少个样本换了结论。"""
    if old_long is None or len(old_long) != len(new_long):
        return {"items": 0, "samples": 0, "comparable": False}
    old_status = old_long["status"].to_numpy()
    new_status = new_long["status"].to_numpy()
    changed_mask = old_status != new_status
    samples = int(pd.unique(new_long.loc[changed_mask, "sample_index"]).size) if changed_mask.any() else 0
    return {"items": int(changed_mask.sum()), "samples": samples, "comparable": True}


def _health_line(cleaned: CleanResult, unit_log: list[str]) -> str:
    """拼"12000 行；剔除 3 行重复；置空 12 个越界值；HGB 单位已归一"这句话。"""
    duplicated = int(cleaned.removed_by_reason.get("duplicate", 0))
    nulled = sum(int(entry.count) for entry in cleaned.log if entry.action == "value_domain")
    unit_note = ("；" + "；".join(unit_log)) if unit_log else ""
    caption = caption_health(
        rows=len(cleaned.frame),
        duplicate_rows=duplicated,
        nulled_cells=nulled,
        unit_note=unit_note,
    )
    return caption.text


def load_artifacts(dataset_id: str, settings: Settings | None = None) -> dict[str, pd.DataFrame]:
    """读回某一数据集已落盘的产物（导出、图表共用）。"""
    settings = settings or get_settings()
    work_dir = settings.processed_dir / dataset_id
    frames: dict[str, pd.DataFrame] = {}
    for key in ("clean", "flagged", "summary"):
        path = work_dir / f"{key}.parquet"
        if path.exists():
            frames[key] = pd.read_parquet(path)
    return frames


def unit_notes(decisions: list[UnitDecision]) -> list[str]:
    return [d.note for d in decisions if d.converted]
