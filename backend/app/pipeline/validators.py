"""S3 校验（SRS 3.6、FR-04、BR-03/04/05）。

本模块只**判定**，不改数据；清洗动作全部在 ``cleaning.py``。这样"报告里说有问题"
与"实际有没有改"用的是同一份证据，不会出现报告说 3 行越界、清洗却删了 5 行的情形。

判定结论只有三种身份，其中第二、三种的区别是本项目的核心（BR-06）：

* 脏数据：值域外、逻辑矛盾、重复 → 可剔除，且**剔除后不得计入异常清单**；
* 异常样本：落在值域内、但超出参考区间 → **必须保留**（判定在 S6 做，这里不碰）；
* 正常样本。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from app.pipeline.fielddict import FieldDictionary, FieldSpec
from app.pipeline.units import UnitDecision

Severity = Literal["ERROR", "WARN", "INFO"]

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_MARKERS = "*#?↑↓↑↑↓↓HL.。"


def extract_number(value: object) -> float | None:
    """从 ``"12.3*" `` ``"<0.5"`` ``"1,000"`` 之类的脏值里取出数值；取不到返回 None。

    这是 BR-03 中"类型修复"的实现，覆盖 ``cleaning_strategy.yaml`` 的
    ``string_numbers.extract_number``。
    """
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return number if np.isfinite(number) else None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "na", "n/a", "-", "--", "null", "none"}:
        return None
    text = text.replace(",", "").replace("，", "").replace(" ", "")
    text = text.strip("<>≤≥=~" + _MARKERS)
    match = _NUM_RE.search(text)
    if not match:
        return None
    try:
        number = float(match.group())
    except ValueError:
        return None
    return number if np.isfinite(number) else None


@dataclass(frozen=True)
class Issue:
    code: str
    field: str | None
    severity: Severity
    count: int
    rows: tuple[int, ...] = ()
    message: str = ""
    fix: str = ""

    def to_payload(self) -> dict:
        return {
            "code": self.code,
            "field": self.field,
            "severity": self.severity,
            "count": self.count,
            "rows_preview": list(self.rows[:10]),
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class QualityReport:
    rows: int
    columns: int
    issues: list[Issue] = field(default_factory=list)
    dq: dict[str, float | None] = field(default_factory=dict)
    completeness: dict[str, float] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(i.count for i in self.issues if i.severity == "ERROR")

    def to_payload(self) -> dict:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "issues": [i.to_payload() for i in self.issues],
            "dq": {k: (None if v is None else round(v, 4)) for k, v in self.dq.items()},
            "completeness": {k: round(v, 4) for k, v in self.completeness.items()},
        }


@dataclass
class Validated:
    """校验结论：一次算出，供质量报告与清洗共用。"""

    source: pd.DataFrame
    numeric: pd.DataFrame
    parse_failed: dict[str, tuple[int, ...]] = field(default_factory=dict)
    domain_violations: dict[str, tuple[int, ...]] = field(default_factory=dict)
    logic_violations: tuple[int, ...] = ()
    duplicate_rows: tuple[int, ...] = ()
    missing_columns: dict[str, int] = field(default_factory=dict)
    #: 每条恒等式各违反了哪些行，键是被"证伪"的那个字段（BR-05 + 两条派生理）
    identity_violations: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def dirty_rows(self) -> set[int]:
        rows: set[int] = set(self.duplicate_rows)
        for values in self.domain_violations.values():
            rows.update(values)
        return rows


def _field_specs(fields: FieldDictionary, frame: pd.DataFrame) -> list[FieldSpec]:
    return [spec for name in frame.columns if (spec := fields.spec(name)) is not None]


def parse_numeric(frame: pd.DataFrame, fields: FieldDictionary) -> tuple[pd.DataFrame, dict[str, tuple[int, ...]]]:
    """把所有已知数值字段转成 float；返回 (数值表, 每列解析失败的原始行号)。

    两段式：先用 ``pd.to_numeric(errors="coerce")`` 走 C 快路径，**只对失败且非空的
    单元格**回退到 ``extract_number`` 正则。十万行 × 20 列的实测差异是 20 s 与
    0.2 s —— 逐格正则会把清洗拖到不可用，而绝大多数单元格本来就是干净的字符串数字。
    """
    numeric = pd.DataFrame(index=frame.index)
    failed: dict[str, tuple[int, ...]] = {}
    for spec in _field_specs(fields, frame):
        if spec.dtype != "float":
            continue
        column = frame[spec.name]
        values = pd.to_numeric(column, errors="coerce")
        # 需要回退正则的格子：转换失败、原本有值、且不是空白字符串
        needs = values.isna() & column.notna()
        if needs.any():
            needs &= ~column.astype(str).str.strip().eq("")
        if needs.any():
            positions = column.index[needs]
            parsed = [extract_number(v) for v in column.loc[positions]]
            values.loc[positions] = [np.nan if v is None else v for v in parsed]
            bad = tuple(int(i) for i, v in zip(positions, parsed, strict=False) if v is None)
            if bad:
                failed[spec.name] = bad
        numeric[spec.name] = values.astype("float64")
    return numeric, failed


def _is_blank(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def find_domain_violations(numeric: pd.DataFrame, fields: FieldDictionary) -> dict[str, tuple[int, ...]]:
    """3.3 值域检查（DQ-03）。值域外即脏数据，不是异常样本（BR-06）。"""
    violations: dict[str, tuple[int, ...]] = {}
    for column in numeric.columns:
        spec = fields.spec(column)
        if spec is None or spec.domain is None:
            continue
        low, high = spec.domain
        series = numeric[column]
        mask = series.notna()
        if low is not None:
            mask &= series >= low
        if high is not None:
            mask &= series <= high
        bad = tuple(int(i) for i in series.index[series.notna() & ~mask])
        if bad:
            violations[column] = bad
    return violations


def find_duplicates(frame: pd.DataFrame) -> tuple[int, ...]:
    """BR-04：全字段完全一致视为重复，保留首条。"""
    if frame.empty:
        return ()
    duplicated = frame.duplicated(keep="first")
    return tuple(int(i) for i in frame.index[duplicated])


IDENTITY_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    # (被证伪的字段, 计算它需要的字段, 现象描述)
    ("hct", ("hct", "rbc", "mcv"), "HCT 与 RBC×MCV/10 偏差超过 15%"),
    ("mch", ("mch", "hgb", "rbc"), "MCH 与 HGB/RBC 偏差超过 15%"),
    ("mchc", ("mchc", "hgb", "hct"), "MCHC 与 HGB/HCT 偏差超过 15%"),
)
"""三条恒等式：HCT≈RBC×MCV/10、MCH=HGB/RBC、MCHC=HGB/HCT。

以前只查第一条。MCH 与 MCHC 是**定义式**，只要 HGB/RBC/HCT 里有一个数错（或整列
错位一格），它们立刻对不上——这是抓"列错位"最便宜的办法：不用额外数据、不用模型。
"""

IDENTITY_TOLERANCE = 0.15


def _identity_ratio(target: str, subset: pd.DataFrame) -> pd.Series:
    """按恒等式算"实测值 / 应有值"，返回每个样本的偏差比例（非负）。"""
    if target == "hct":
        expected = subset["rbc"] * subset["mcv"] / 10
    elif target == "mch":
        expected = subset["hgb"] / subset["rbc"]
    else:  # mchc：hct 是百分数，换算成小数
        expected = subset["hgb"] / (subset["hct"] / 100)
    actual = subset[target]
    safe = expected.where(expected.abs() > 0, np.nan)
    return ((actual - safe) / safe).abs()


def find_logic_violations(numeric: pd.DataFrame) -> dict[str, tuple[int, ...]]:
    """BR-05 + 两条派生理：逐条恒等式找出对不上的行。

    返回 ``{被证伪的字段: (行号, ...)}``。只在所需字段齐全、且分母非零时计算；
    不齐全不是违规，是"无法判"——把"无法判"当成"有问题"会凭空删掉正常数据。
    """
    violations: dict[str, tuple[int, ...]] = {}
    for target, needed, _message in IDENTITY_RULES:
        if not set(needed).issubset(set(numeric.columns)):
            continue
        subset = numeric[list(needed)].dropna()
        if target == "hct":
            subset = subset[subset["hct"] > 0]
        else:
            subset = subset[subset["rbc"] > 0] if target == "mch" else subset[subset["hct"] > 0]
        if subset.empty:
            continue
        ratio = _identity_ratio(target, subset)
        rows = tuple(int(i) for i in subset.index[ratio > IDENTITY_TOLERANCE])
        if rows:
            violations[target] = rows
    return violations


def validate(
    frame: pd.DataFrame,
    fields: FieldDictionary,
    *,
    unit_decisions: list[UnitDecision] | None = None,
) -> tuple[Validated, QualityReport]:
    numeric, failed = parse_numeric(frame, fields)
    domain = find_domain_violations(numeric, fields)
    duplicates = find_duplicates(frame)
    identity = find_logic_violations(numeric)
    logic = tuple(sorted({row for rows in identity.values() for row in rows}))

    completeness: dict[str, float] = {}
    for column in frame.columns:
        completeness[column] = float(frame[column].notna().mean()) if len(frame) else 0.0

    validated = Validated(
        source=frame,
        numeric=numeric,
        parse_failed=failed,
        domain_violations=domain,
        logic_violations=logic,
        duplicate_rows=duplicates,
        missing_columns={c: int(v) for c, v in frame.isna().sum().items()},
        identity_violations=identity,
    )
    report = build_report(frame, fields, validated, unit_decisions)
    return validated, report


def build_report(
    frame: pd.DataFrame,
    fields: FieldDictionary,
    validated: Validated,
    unit_decisions: list[UnitDecision] | None = None,
) -> QualityReport:
    rows = len(frame)
    issues: list[Issue] = []

    # --- 缺失（BR-03 / DQ-01）---
    completeness: dict[str, float] = {}
    for spec in _field_specs(fields, frame):
        rate = 1.0 - float(validated.source[spec.name].isna().mean())
        completeness[spec.name] = rate
        missing = int(validated.source[spec.name].isna().sum())
        if missing == 0:
            continue
        threshold = 0.30
        if rate < 1 - threshold:
            issues.append(
                Issue(
                    code="BR-03",
                    field=spec.name,
                    severity="WARN",
                    count=missing,
                    message=f"{spec.name} 缺失率 {1 - rate:.1%} 超过 30%，整列剔除",
                    fix="整列剔除",
                )
            )
        else:
            issues.append(
                Issue(
                    code="DQ-01",
                    field=spec.name,
                    severity="INFO",
                    count=missing,
                    message=f"{spec.name} 缺失 {missing} 行（{1 - rate:.1%}），按性别+年龄段中位数填充",
                    fix="中位数填充",
                )
            )

    core_missing = [
        name
        for name in ("hgb", "wbc", "plt")
        if name in frame.columns and validated.source[name].isna().all()
    ]
    if core_missing:
        issues.append(
            Issue(
                code="BR-03",
                field=None,
                severity="ERROR",
                count=rows,
                message="核心指标整列为空：" + "、".join(core_missing),
                fix="请重新上传或检查字段映射",
            )
        )

    # --- 值域（DQ-03 / BR-06）---
    for name, bad in validated.domain_violations.items():
        spec = fields.spec(name)
        domain = spec.domain if spec else (None, None)
        issues.append(
            Issue(
                code="DQ-03",
                field=name,
                severity="ERROR",
                count=len(bad),
                rows=bad,
                message=f"{name} 有 {len(bad)} 行超出值域 {domain}，判为录入错误",
                fix="置空（不删除整行）",
            )
        )

    # --- 解析失败 ---
    for name, bad in validated.parse_failed.items():
        issues.append(
            Issue(
                code="DQ-03",
                field=name,
                severity="WARN",
                count=len(bad),
                rows=bad,
                message=f"{name} 有 {len(bad)} 行无法解析为数值",
                fix="置空",
            )
        )

    # --- 重复（BR-04）---
    if validated.duplicate_rows:
        issues.append(
            Issue(
                code="BR-04",
                field=None,
                severity="ERROR",
                count=len(validated.duplicate_rows),
                rows=validated.duplicate_rows,
                message=f"{len(validated.duplicate_rows)} 行与其他行全字段完全重复",
                fix="保留首条",
            )
        )

    # --- 逻辑一致性（BR-05 + MCH/MCHC 两条派生理）---
    for target, _needed, message in IDENTITY_RULES:
        rows_hit = validated.identity_violations.get(target, ())
        if not rows_hit:
            continue
        issues.append(
            Issue(
                code="BR-05",
                field=target,
                severity="ERROR",
                count=len(rows_hit),
                rows=rows_hit,
                message=f"{len(rows_hit)} 行 {message}",
                fix=f"{target} 置空",
            )
        )

    dq = _dq_metrics(frame, fields, validated, unit_decisions)
    return QualityReport(rows=rows, columns=len(frame.columns), issues=issues, dq=dq, completeness=completeness)


def _dq_metrics(
    frame: pd.DataFrame,
    fields: FieldDictionary,
    validated: Validated,
    unit_decisions: list[UnitDecision] | None,
) -> dict[str, float | None]:
    rows = len(frame)
    dq: dict[str, float | None] = {}

    # DQ-01 完整率：取核心字段最小值（3.6 只对核心字段设合格线）
    core = [c for c in ("hgb", "wbc", "plt") if c in frame.columns]
    if core:
        dq["DQ-01"] = min(float(frame[c].notna().mean()) for c in core)
    else:
        dq["DQ-01"] = None

    # DQ-02 唯一率
    dq["DQ-02"] = (rows - len(validated.duplicate_rows)) / rows if rows else None

    # DQ-03 有效率：值域内行数 ÷ 非空行数（按全部数值列汇总）
    total_nonnull = int(validated.numeric.notna().sum().sum())
    total_bad = sum(
        len(v) for v in (list(validated.domain_violations.values()) + list(validated.parse_failed.values()))
    )
    dq["DQ-03"] = (total_nonnull - total_bad) / total_nonnull if total_nonnull else None

    # DQ-04 单位一致率：需要单位判定结果，由调用方提供
    if unit_decisions is None:
        dq["DQ-04"] = None
    else:
        judged = [d for d in unit_decisions if d.median is not None]
        dq["DQ-04"] = (
            sum(1 for d in judged if not d.ambiguous) / len(judged) if judged else None
        )

    # DQ-05 逻辑一致率
    needed = {"hct", "rbc", "mcv"}
    if needed.issubset(set(validated.numeric.columns)):
        subset = validated.numeric[list(needed)].dropna()
        subset = subset[subset["hct"] > 0]
        dq["DQ-05"] = (
            1.0 - len(validated.logic_violations) / len(subset) if len(subset) else None
        )
    else:
        dq["DQ-05"] = None

    # DQ-06 异常率：判定在 S6 之后，这里留空
    dq["DQ-06"] = None
    return dq
