"""S2 字段映射（SRS 3.3、FR-02）。

四级策略：
1. 标准名全等           → confidence 1.00
2. 别名表（归一化后）   → confidence 0.95
3. 相似度 ≥ 0.75        → 待确认（阻塞上传，4.2.0 的两处阻塞点之一）
4. 都不中               → 未识别，允许忽略

判定"是否阻塞"只有两条：**必填指标不足** 或 **存在待确认的模糊匹配**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.pipeline.fielddict import FieldDictionary, MappingConfig

FUZZY_THRESHOLD = 0.75
_STRIP = re.compile(r"[\s_\-()（）\[\]/\\.]+")


def normalize(name: str) -> str:
    """大小写不敏感，去除空格、下划线、连字符与括号（3.3 规则 2）。"""
    return _STRIP.sub("", str(name)).strip().lower()


@dataclass(frozen=True)
class ColumnMatch:
    source: str
    target: str | None
    confidence: float
    method: str  # exact | alias | fuzzy | ignored
    candidates: tuple[tuple[str, float], ...] = ()

    @property
    def needs_confirm(self) -> bool:
        return self.method == "fuzzy"


@dataclass
class MappingResult:
    matches: list[ColumnMatch] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)
    unresolved: list[ColumnMatch] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def needs_confirmation(self) -> bool:
        """FR-02：只有这两种情况才阻塞用户。"""
        return bool(self.missing_required) or bool(self.unresolved)

    def targets(self) -> set[str]:
        return set(self.mapping.values())

    def to_payload(self) -> dict:
        return {
            "mapping": self.mapping,
            "items": [
                {
                    "source": m.source,
                    "target": m.target,
                    "confidence": round(m.confidence, 2),
                    "method": m.method,
                    "needs_confirm": m.needs_confirm,
                    "candidates": [{"target": t, "score": round(s, 2)} for t, s in m.candidates],
                }
                for m in self.matches
            ],
            "unresolved": [m.source for m in self.unresolved],
            "missing_required": self.missing_required,
            "ignored": self.ignored,
            "needs_confirmation": self.needs_confirmation,
        }


class FieldMapper:
    def __init__(self, fields: FieldDictionary, config: MappingConfig):
        self._fd = fields
        self._cfg = config
        # 归一化后的查找表：前者为标准名，后者为别名（不覆盖标准名）
        self._index: dict[str, tuple[str, str]] = {}
        for target in fields.fields:
            self._index[normalize(target)] = (target, "exact")
        for target, aliases in config.aliases.items():
            if target not in fields.fields:
                continue
            for alias in aliases:
                self._index.setdefault(normalize(alias), (target, "alias"))

    def suggest(self, columns: list[str]) -> MappingResult:
        result = MappingResult()
        claimed: dict[str, ColumnMatch] = {}

        for column in columns:
            hit = self._index.get(normalize(column))
            if hit is None:
                continue
            target, method = hit
            match = ColumnMatch(
                source=column,
                target=target,
                confidence=1.0 if method == "exact" and column == target else 0.95,
                method=method,
            )
            self._claim(result, claimed, match)

        # 第二遍：对未识别的列做相似度匹配
        for column in columns:
            if normalize(column) in self._index:
                continue
            candidates = self._fuzzy_candidates(column)
            if not candidates:
                result.matches.append(ColumnMatch(column, None, 0.0, "ignored"))
                result.ignored.append(column)
                continue
            target, score = candidates[0]
            match = ColumnMatch(
                source=column,
                target=target,
                confidence=score,
                method="fuzzy",
                candidates=tuple(candidates[:3]),
            )
            if target in claimed:
                # 同名列已由更高置信度占用 → 不自动抢占，交用户确认
                result.unresolved.append(match)
                result.matches.append(ColumnMatch(column, None, score, "fuzzy", tuple(candidates[:3])))
                result.ignored.append(column)
                continue
            self._claim(result, claimed, match)
            result.unresolved.append(match)

        # 必填指标是否足够（FR-02：至少 3 个血液指标）
        metric_targets = {t for t in result.mapping.values() if self._fd.spec(t) and self._fd.spec(t).is_metric}
        if len(metric_targets) < self._fd.required.min_metrics:
            result.missing_required = [
                name for name in self._fd.required.core_metrics if name not in metric_targets
            ]
            if not result.missing_required:
                result.missing_required = list(self._fd.metric_fields())[: self._fd.required.min_metrics]

        if result.ignored:
            result.notes.append(f"{len(result.ignored)} 列未识别，已忽略：" + "、".join(result.ignored[:5]))
        return result

    # --- 内部 ---

    @staticmethod
    def _claim(result: MappingResult, claimed: dict[str, ColumnMatch], match: ColumnMatch) -> None:
        if match.target is None:
            result.matches.append(match)
            return
        claimed[match.target] = match
        result.matches.append(match)
        result.mapping[match.source] = match.target

    def _fuzzy_candidates(self, column: str) -> list[tuple[str, float]]:
        key = normalize(column)
        if not key:
            return []
        scored: dict[str, float] = {}
        for normalized, (target, _method) in self._index.items():
            score = SequenceMatcher(None, key, normalized).ratio()
            if score >= FUZZY_THRESHOLD and score > scored.get(target, 0.0):
                scored[target] = score
        return sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
