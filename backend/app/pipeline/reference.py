"""参考区间（SRS 3.5、附录 A、BR-01、BR-17）。

本模块是"偏高 / 正常 / 偏低"的唯一判定入口。三个不能被绕开的语义：

1. **闭区间**（BR-01）：``low <= x <= high`` 为 NORMAL，边界值属于正常。
2. **性别绑定**（3.5）：女性 hgb/rbc/hct 走 ``female_overrides``。
3. **缺失不猜测**（BR-17）：性别缺失时，依赖性别的指标返回 ``None`` + ``gender_missing``，
   由调用方判为 NA；**绝不**回退到男性区间。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml


class MetricStatus(StrEnum):
    """指标三态 + 未判定（1.4「指标状态」）。

    BR-14 要求三通道表达，因此每个状态必须能同时给出：颜色 token（第一通道）、
    符号（第二通道）、中文文字（第三通道）。只返回颜色枚举即视为不合格实现。
    """

    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    NA = "NA"

    @property
    def symbol(self) -> str:
        return {"HIGH": "↑", "NORMAL": "—", "LOW": "↓", "NA": "∅"}[self.value]

    @property
    def text_cn(self) -> str:
        return {"HIGH": "偏高", "NORMAL": "正常", "LOW": "偏低", "NA": "未判定"}[self.value]

    @property
    def color_token(self) -> str:
        """返回设计 token 名而非十六进制色值（NFR-M-07：颜色单一来源）。"""
        return {
            "HIGH": "color-status-high",
            "NORMAL": "color-status-normal",
            "LOW": "color-status-low",
            "NA": "color-status-na",
        }[self.value]


@dataclass(frozen=True)
class Interval:
    """一个指标的参考区间，已绑定到具体性别版本。"""

    metric: str
    low: float
    high: float
    unit: str
    name_cn: str
    gender: str | None = None

    @property
    def width(self) -> float:
        return self.high - self.low

    def judge(self, value: float | None) -> MetricStatus:
        """BR-01 闭区间判定。缺失或非有限值一律 NA。"""
        if value is None or value != value:  # NaN 自身不等于自身
            return MetricStatus.NA
        if value < self.low:
            return MetricStatus.LOW
        if value > self.high:
            return MetricStatus.HIGH
        return MetricStatus.NORMAL

    def deviation_pct(self, value: float | None) -> float:
        """BR-08 的单项偏离：越界距离 ÷ 区间宽度 × 100；未越界为 0。"""
        if value is None or value != value:
            return 0.0
        if value < self.low:
            distance = self.low - value
        elif value > self.high:
            distance = value - self.high
        else:
            return 0.0
        if self.width <= 0:
            return 0.0
        return round(distance / self.width * 100, 2)

    def pos(self, value: float) -> float:
        """FR-31 的标准化位置：``(x - low) / (high - low)``。

        所有指标共用同一坐标系，越界值 pos < 0 或 > 1 按同一比例延伸——这样
        "越界程度"才是可比的，而不会被 HGB(~140) 与 MCH(~30) 的量纲差放大（RK-17）。
        """
        if self.width <= 0:
            return 0.0
        return round((value - self.low) / self.width, 4)

    def ratio_to_bound(self, value: float | None) -> float | None:
        """FR-31 的人话文案倍数：偏高取 ``x / high``，偏低取 ``low / x``。

        与 BR-08 的 severity 口径不同：severity 按区间宽度归一用于排序，
        ratio_to_bound 按边界倍数用于文案，两者不得互相替代（FR-31 表格）。
        """
        if value is None or value != value or value <= 0:
            return None
        status = self.judge(value)
        if status is MetricStatus.HIGH:
            return round(value / self.high, 2) if self.high else None
        if status is MetricStatus.LOW:
            return round(self.low / value, 2) if value else None
        return 1.0


@dataclass(frozen=True)
class ReferenceRanges:
    """一份参考区间配置（带版本号）。"""

    version: str
    source: str
    applies_to: dict
    default: dict[str, Interval]
    female_overrides: dict[str, Interval]

    # --- 构造 ---

    @classmethod
    def from_dict(cls, raw: dict) -> ReferenceRanges:
        default = {
            metric: Interval(
                metric=metric,
                low=float(spec["low"]),
                high=float(spec["high"]),
                unit=str(spec.get("unit", "")),
                name_cn=str(spec.get("name_cn", metric)),
                gender=None,
            )
            for metric, spec in (raw.get("default") or {}).items()
        }
        female: dict[str, Interval] = {}
        for metric, spec in (raw.get("female_overrides") or {}).items():
            base = default.get(metric)
            female[metric] = Interval(
                metric=metric,
                low=float(spec["low"]),
                high=float(spec["high"]),
                unit=str(spec.get("unit", base.unit if base else "")),
                name_cn=str(spec.get("name_cn", base.name_cn if base else metric)),
                gender="female",
            )
        return cls(
            version=str(raw.get("version", "")),
            source=str(raw.get("source", "")),
            applies_to=dict(raw.get("applies_to") or {}),
            default=default,
            female_overrides=female,
        )

    @classmethod
    def load(cls, path: str | Path) -> ReferenceRanges:
        with Path(path).open(encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})

    # --- 查询 ---

    def metrics(self) -> tuple[str, ...]:
        return tuple(self.default)

    def gender_dependent(self, metric: str) -> bool:
        """该指标是否存在性别差异（hgb / rbc / hct）。"""
        return metric in self.female_overrides

    def resolve(self, metric: str, gender: str | None) -> tuple[Interval | None, str | None]:
        """返回 ``(区间, 未判定原因)``。

        ``reason`` 取值：``no_interval``（配置里没有该指标）、``gender_missing``（BR-17）。
        """
        base = self.default.get(metric)
        if base is None:
            return None, "no_interval"
        if self.gender_dependent(metric):
            if gender == "female":
                return self.female_overrides[metric], None
            if gender == "male":
                return base, None
            # BR-17：不得套用任一性别区间
            return None, "gender_missing"
        return base, None

    def interval(self, metric: str, gender: str | None = None) -> Interval | None:
        return self.resolve(metric, gender)[0]

    def snapshot(self) -> dict:
        """入库只读快照（7.5：报告需绑定当时版本）。"""

        def dump(item: Interval) -> dict:
            return {"low": item.low, "high": item.high, "unit": item.unit, "name_cn": item.name_cn}

        return {
            "version": self.version,
            "source": self.source,
            "applies_to": self.applies_to,
            "default": {k: dump(v) for k, v in self.default.items()},
            "female_overrides": {k: dump(v) for k, v in self.female_overrides.items()},
        }


_CACHE: dict[tuple[str, float], ReferenceRanges] = {}
_CACHE_LOCK = threading.Lock()


def load_ranges(path: str | Path) -> ReferenceRanges:
    """按 (路径, mtime) 缓存加载。测试里换 YAML 不会读到旧内容。"""
    p = Path(path)
    key = (str(p.resolve()), p.stat().st_mtime)
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    ranges = ReferenceRanges.load(p)
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE[key] = ranges
    return ranges
