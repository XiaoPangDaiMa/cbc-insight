"""S4 清洗（SRS FR-05、BR-03/04/05/06、``cleaning_strategy.yaml``）。

顺序不能随便换，每一步都在为下一步消除噪声：

1. 类型修复（``12.3*`` → ``12.3``）——否则后面所有比较都在字符串上做；
2. 值域外置空——脏值必须在填缺失**之前**清掉，否则会被中位数"救活"；
3. 整列剔除（缺失率 > 30%）；
4. 去重——先于填充，因为填充会让本不相同的两行变得相同；
5. 逻辑一致性（hct 置空）；
6. 删除核心字段全空的行；
7. 缺失填充（性别+年龄段中位数）。

**任何删除都不许碰"数据本身异常但取值合法"的行**（BR-06）。HGB=85 的男性会被
``removed_by_reason`` 之外的路径完整保留到 S6 去判定。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.pipeline.derive import derive
from app.pipeline.fielddict import FieldDictionary, MappingConfig
from app.pipeline.validators import Validated, extract_number

CORE_FIELDS: tuple[str, ...] = ("hgb", "wbc", "plt")


@dataclass(frozen=True)
class CleanLogEntry:
    step: int
    action: str
    field: str | None
    count: int
    detail: str = ""

    def to_payload(self) -> dict:
        return {
            "step": self.step,
            "action": self.action,
            "field": self.field,
            "count": self.count,
            "detail": self.detail,
        }


@dataclass
class StageSnapshot:
    rows: int
    columns: int
    missing_rate: float
    core_completeness: float

    def to_payload(self) -> dict:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "missing_rate": round(self.missing_rate, 4),
            "core_completeness": round(self.core_completeness, 4),
        }


@dataclass
class CleanResult:
    frame: pd.DataFrame
    log: list[CleanLogEntry] = field(default_factory=list)
    before: StageSnapshot | None = None
    after: StageSnapshot | None = None
    removed_by_reason: dict[str, int] = field(default_factory=dict)
    dropped_columns: list[str] = field(default_factory=list)
    filled: dict[str, int] = field(default_factory=dict)

    @property
    def rows_removed(self) -> int:
        return sum(self.removed_by_reason.values())

    def to_payload(self) -> dict:
        return {
            "before": self.before.to_payload() if self.before else None,
            "after": self.after.to_payload() if self.after else None,
            "log": [e.to_payload() for e in self.log],
            "removed_by_reason": self.removed_by_reason,
            "dropped_columns": self.dropped_columns,
            "filled": self.filled,
        }


def _snapshot(frame: pd.DataFrame) -> StageSnapshot:
    total_cells = int(frame.shape[0] * frame.shape[1]) if frame.shape[0] else 0
    missing = float(frame.isna().sum().sum() / total_cells) if total_cells else 0.0
    core = [c for c in CORE_FIELDS if c in frame.columns]
    completeness = (
        float(min(frame[c].notna().mean() for c in core)) if core and len(frame) else 0.0
    )
    return StageSnapshot(len(frame), len(frame.columns), missing, completeness)


def clean(
    source: pd.DataFrame,
    validated: Validated,
    fields: FieldDictionary,
    config: MappingConfig,
    *,
    missing_column_threshold: float = 0.30,
) -> CleanResult:
    result = CleanResult(frame=source.copy(), before=_snapshot(source))
    frame = result.frame
    log: list[CleanLogEntry] = []
    removed: dict[str, int] = {}

    # --- 1. 类型修复 ---
    typed_cells = 0
    for column in validated.numeric.columns:
        original = frame[column]
        converted = validated.numeric[column]
        changed = int((original.notna() & converted.notna() & (original.astype(str) != converted.astype(str))).sum())
        frame[column] = converted
        typed_cells += changed
    if typed_cells:
        log.append(CleanLogEntry(1, "type_repair", None, typed_cells, "字符串数字已转为数值"))

    # --- 2. 值域外置空 ---
    for column, bad in validated.domain_violations.items():
        if not bad:
            continue
        frame.loc[list(bad), column] = np.nan
        log.append(
            CleanLogEntry(2, "value_domain", column, len(bad), "超出值域的值已置空（记为脏数据）")
        )

    # --- 3. 整列剔除 ---
    # 例外：核心字段（hgb/wbc/plt）不参与整列剔除。它们既是判定输入（FR-16）也是
    # 异常识别输入（FR-17），删掉整列会让 S6 输出"没有任何异常"，而用户看到的是
    # 一份干净的报告——这比报错更危险。改为保留并记一条告警，由质量报告提示
    # "核心指标缺失率过高，判定结果可靠性下降"（对应 SRS 3.6 DQ 缺口，见交付说明）。
    for column in list(frame.columns):
        if column not in validated.numeric.columns and column not in {"gender", "age"}:
            continue
        rate = float(frame[column].isna().mean()) if len(frame) else 0.0
        if rate <= missing_column_threshold:
            continue
        if column in CORE_FIELDS:
            log.append(
                CleanLogEntry(
                    3,
                    "keep_core_column",
                    column,
                    len(frame),
                    f"核心字段缺失率 {rate:.1%} > {missing_column_threshold:.0%}，保留整列并告警",
                )
            )
            continue
        frame.drop(columns=[column], inplace=True)
        result.dropped_columns.append(column)
        log.append(
            CleanLogEntry(3, "drop_column", column, len(source), f"缺失率 {rate:.1%} > {missing_column_threshold:.0%}")
        )

    # --- 4. 去重（保留首条）---
    if validated.duplicate_rows:
        # 注意：不要把 set(...) 写在推导式里——那样每一行都会重建一次集合，
        # 十万行 × 两万个重复行就是二十亿次插入（实测这一行曾占 S4 的 260 s）。
        drop_index = pd.Index(validated.duplicate_rows)
        frame = frame.loc[~frame.index.isin(drop_index)]
        removed["duplicate"] = len(validated.duplicate_rows)
        log.append(CleanLogEntry(4, "dedupe", None, len(validated.duplicate_rows), "全字段重复，保留首条"))

    # --- 5. 逻辑一致性：hct 置空 ---
    if validated.logic_violations and "hct" in frame.columns:
        rows = [i for i in validated.logic_violations if i in frame.index]
        frame.loc[rows, "hct"] = np.nan
        log.append(CleanLogEntry(5, "logic_hct", "hct", len(rows), "HCT 与 RBC×MCV/10 偏差 > 15%，hct 置空"))

    # --- 6. 删除核心字段全空的行 ---
    present_core = [c for c in CORE_FIELDS if c in frame.columns]
    if present_core:
        empty_mask = frame[present_core].isna().all(axis=1)
        n_empty = int(empty_mask.sum())
        if n_empty:
            frame.drop(index=frame.index[empty_mask], inplace=True)
            removed["core_all_null"] = n_empty
            log.append(CleanLogEntry(6, "drop_row", None, n_empty, "核心字段（hgb/wbc/plt）全空"))

    # --- 7. 缺失填充：性别+年龄段中位数 ---
    frame = _fill_missing(frame, fields, config, log, result)

    # --- 8. 派生 ---
    frame = derive(frame)
    frame = frame.reset_index(drop=True)

    result.frame = frame
    result.log = log
    result.removed_by_reason = removed
    result.after = _snapshot(frame)
    return result


def _fill_missing(
    frame: pd.DataFrame,
    fields: FieldDictionary,
    config: MappingConfig,
    log: list[CleanLogEntry],
    result: CleanResult,
) -> pd.DataFrame:
    if "gender" in frame.columns:
        frame["gender"] = [config.canonical_gender(v) for v in frame["gender"]]
    if "age" in frame.columns:
        frame["age"] = [extract_number(v) for v in frame["age"]]

    frame = frame.copy()
    if "age" in frame.columns:
        from app.pipeline.derive import age_band as _band

        frame["age_band"] = [_band(v) for v in frame["age"]]
    else:
        frame["age_band"] = "Unknown"

    group_keys = [k for k in ("gender", "age_band") if k in frame.columns]
    numeric_columns = [
        c for c in frame.columns if c in fields.fields and fields.spec(c) and fields.spec(c).dtype == "float"
    ]

    for column in numeric_columns:
        missing = int(frame[column].isna().sum())
        if not missing:
            continue
        overall = frame[column].median()
        if group_keys:
            grouped = frame.groupby(group_keys, dropna=False)[column].transform("median")
            frame[column] = frame[column].fillna(grouped)
        frame[column] = frame[column].fillna(overall)
        still = int(frame[column].isna().sum())
        filled = missing - still
        if filled:
            result.filled[column] = filled
            log.append(
                CleanLogEntry(
                    7,
                    "fill_median",
                    column,
                    filled,
                    f"按 {'+'.join(group_keys)} 中位数填充（整体中位数 {overall:.4g}）",
                )
            )
    return frame
