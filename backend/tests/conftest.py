"""测试公共夹具（SRS 10.2 / 10.3）。

约定：

* 单元测试**不连数据库、不连 Redis**（10.3：`-m "not integration"` 应 ≤ 10 s）；
* 需要集成依赖的用例一律标 `@pytest.mark.integration`，连接不上必须在集成层明确报错，
  不允许静默 skip（RK-24——"假绿"比没有测试更危险）；
* 10 行夹具的答案写在测试里而不是手工核对：改夹具就必须改断言，二者不会悄悄脱节。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:  # 让 `pytest` 在 backend/ 下直接可跑
    sys.path.insert(0, str(BACKEND_DIR))

from app.pipeline.cleaning import CleanResult, clean  # noqa: E402
from app.pipeline.fielddict import FieldDictionary, MappingConfig  # noqa: E402
from app.pipeline.mapping import FieldMapper, MappingResult  # noqa: E402
from app.pipeline.reading import ReadResult, read_csv  # noqa: E402
from app.pipeline.reference import ReferenceRanges, load_ranges  # noqa: E402
from app.pipeline.rules import flag_frame  # noqa: E402
from app.pipeline.units import UnitDecision, apply_decisions, detect_all  # noqa: E402
from app.pipeline.validators import QualityReport, Validated, validate  # noqa: E402

RESOURCES = BACKEND_DIR / "resources"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@dataclass
class PipelineResult:
    """一次 S1–S6 的完整产物，测试直接断言它，避免每个用例各自拼装。"""

    read: ReadResult
    mapping: MappingResult
    typed: pd.DataFrame
    decisions: list[UnitDecision] = field(default_factory=list)
    validated: Validated | None = None
    report: QualityReport | None = None
    cleaned: CleanResult | None = None
    long: pd.DataFrame | None = None
    summary: pd.DataFrame | None = None

    @property
    def frame(self) -> pd.DataFrame:
        """清洗后的宽表（含 age_band / sample_index）。"""
        assert self.cleaned is not None
        return self.cleaned.frame


def run_pipeline(
    path: Path,
    fields: FieldDictionary,
    config: MappingConfig,
    ranges: ReferenceRanges,
    *,
    mapping: dict[str, str] | None = None,
    metrics: tuple[str, ...] | None = None,
) -> PipelineResult:
    read = read_csv(path)
    mapper = FieldMapper(fields, config)
    suggested = mapper.suggest(read.columns)
    resolved = mapping or suggested.mapping
    typed = read.frame.rename(columns=resolved)
    keep = [c for c in typed.columns if c in fields.fields]
    typed = typed[keep]

    decisions = detect_all(typed, fields.metric_fields())
    converted, _log = apply_decisions(typed, decisions)

    validated, report = validate(converted, fields, unit_decisions=decisions)
    cleaned = clean(converted, validated, fields, config)
    long, summary = flag_frame(cleaned.frame, ranges, metrics=metrics)

    return PipelineResult(
        read=read,
        mapping=suggested,
        typed=converted,
        decisions=decisions,
        validated=validated,
        report=report,
        cleaned=cleaned,
        long=long,
        summary=summary,
    )


@pytest.fixture(scope="session")
def fields() -> FieldDictionary:
    return FieldDictionary.load(RESOURCES / "field_dict.yaml")


@pytest.fixture(scope="session")
def mapping_config() -> MappingConfig:
    return MappingConfig.load(RESOURCES / "field_mapping.yaml")


@pytest.fixture(scope="session")
def ranges() -> ReferenceRanges:
    return load_ranges(RESOURCES / "reference_ranges.yaml")


@pytest.fixture
def clean_csv() -> Path:
    return FIXTURES / "sample_clean.csv"


@pytest.fixture
def dirty_csv() -> Path:
    return FIXTURES / "sample_dirty.csv"


@pytest.fixture
def pipeline(fields, mapping_config, ranges):
    def _run(path: Path, **kwargs) -> PipelineResult:
        return run_pipeline(path, fields, mapping_config, ranges, **kwargs)

    return _run
