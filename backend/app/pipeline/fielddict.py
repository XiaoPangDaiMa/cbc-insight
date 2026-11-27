"""字段字典与字段映射（SRS 3.3）。

两份 YAML 各管一件事，互不重复：

* ``field_dict.yaml``：标准字段名、类型、单位、合理值域、可空、中文名、显示顺序、小数位。
* ``field_mapping.yaml``：别名表、性别取值映射、年龄区间正则。

3.3 的四级匹配策略在 ``mapping.FieldMapper`` 里实现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FieldSpec:
    name: str
    dtype: str  # int | float | enum
    unit: str
    domain: tuple[float, float] | None
    nullable: bool
    name_cn: str
    enum: tuple[str, ...] | None = None
    check_only: bool = False
    """只用于交叉校验、不参与判定的字段（v1.9：五分类绝对值）。

    它们有参考价值的地方是"能独立复算一次百分比"（NE# ≈ WBC × NE% / 100），
    而不是"这个人的中性粒细胞高不高"——后者看百分比就够，而给绝对值配区间
    等于凭空多出一套标准。所以把它们标成 check_only：可以映射进来做校验，
    但永远不进判定、指标卡、图表与异常清单。
    """

    @property
    def is_metric(self) -> bool:
        """血液指标（可参与"偏高 / 偏低"判定的数值字段）。"""
        return self.dtype == "float" and not self.check_only

    def in_domain(self, value: float) -> bool:
        if self.domain is None:
            return True
        low, high = self.domain
        return low <= value <= high


@dataclass(frozen=True)
class RequiredFields:
    min_metrics: int
    core_metrics: tuple[str, ...]


@dataclass(frozen=True)
class FieldDictionary:
    fields: dict[str, FieldSpec]
    display_order: tuple[str, ...]
    decimals: dict[str, int]
    required: RequiredFields

    @classmethod
    def load(cls, path: str | Path) -> FieldDictionary:
        with Path(path).open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        fields: dict[str, FieldSpec] = {}
        for name, spec in (raw.get("fields") or {}).items():
            domain = spec.get("domain")
            fields[name] = FieldSpec(
                name=name,
                dtype=str(spec.get("dtype", "float")),
                unit=str(spec.get("unit", "")),
                domain=tuple(domain) if domain else None,  # type: ignore[arg-type]
                nullable=bool(spec.get("nullable", True)),
                name_cn=str(spec.get("name_cn", name)),
                enum=tuple(spec["enum"]) if spec.get("enum") else None,
                check_only=bool(spec.get("check_only", False)),
            )
        req = raw.get("required_fields") or {}
        return cls(
            fields=fields,
            display_order=tuple(raw.get("display_order") or fields),
            decimals={k: int(v) for k, v in (raw.get("decimals") or {}).items()},
            required=RequiredFields(
                min_metrics=int(req.get("min_metrics", 3)),
                core_metrics=tuple(req.get("core_metrics") or ("hgb", "wbc", "plt")),
            ),
        )

    def spec(self, name: str) -> FieldSpec | None:
        return self.fields.get(name)

    def metric_fields(self) -> tuple[str, ...]:
        """按 display_order 排列的血液指标。"""
        return tuple(n for n in self.display_order if n in self.fields and self.fields[n].is_metric)

    def check_fields(self) -> tuple[str, ...]:
        """只做交叉校验的字段（v1.9 五分类绝对值），按 display_order 排列。"""
        return tuple(n for n in self.display_order if n in self.fields and self.fields[n].check_only)

    def name_cn(self, name: str) -> str:
        spec = self.fields.get(name)
        return spec.name_cn if spec else name

    def unit(self, name: str) -> str:
        spec = self.fields.get(name)
        return spec.unit if spec else ""

    def decimals_of(self, name: str) -> int:
        return self.decimals.get(name, 2)


@dataclass(frozen=True)
class MappingConfig:
    """``field_mapping.yaml`` 的解析结果。"""

    aliases: dict[str, tuple[str, ...]]  # 标准字段 -> 别名
    gender_values: dict[str, tuple[str, ...]]  # male/female/unknown -> 原值
    age_range_pattern: re.Pattern

    @classmethod
    def load(cls, path: str | Path) -> MappingConfig:
        with Path(path).open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        aliases = {
            target: tuple(str(a) for a in values if a is not None)
            for target, values in (raw.get("aliases") or {}).items()
        }
        gender_values = {
            target: tuple(str(a).lower() for a in values if a is not None)
            for target, values in (raw.get("gender_values") or {}).items()
        }
        pattern = raw.get("age_range_pattern") or r"^\s*(\d+)\s*[-–~至]\s*(\d+)\s*$"
        return cls(
            aliases=aliases,
            gender_values=gender_values,
            age_range_pattern=re.compile(pattern),
        )

    def canonical_gender(self, raw_value: object) -> str | None:
        """把 M/F、男/女、1/2 归一为 male/female/unknown；无法识别返回 None。"""
        if raw_value is None:
            return None
        text = str(raw_value).strip().lower()
        if text == "" or text == "nan":
            return None
        for canonical, values in self.gender_values.items():
            if text in values:
                return canonical
        if text in {"男", "男性"}:
            return "male"
        if text in {"女", "女性"}:
            return "female"
        return None
