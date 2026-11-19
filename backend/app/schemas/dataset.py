"""数据集相关请求模型（SRS 8.1、FR-01/02/14/24）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConfirmMappingRequest(BaseModel):
    """PUT /datasets/{id}/mapping：``{"mapping": {"HGB(g/L)": "hgb"}}``。"""

    mapping: dict[str, str | None] = Field(default_factory=dict)
    forced_units: dict[str, str] = Field(default_factory=dict)


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class FilterClause(BaseModel):
    metric: str
    op: Literal["lt", "lte", "gt", "gte", "eq", "between"] = "gte"
    value: float | None = None
    upper: float | None = None


class QueryRequest(BaseModel):
    """POST /datasets/{id}/query（FR-14 条件筛选）。"""

    filters: list[FilterClause] = Field(default_factory=list)
    age_min: float | None = None
    age_max: float | None = None
    gender: Literal["male", "female"] | None = None
    stage: Literal["raw", "cleaned"] = "cleaned"
    page: int = 1
    size: int = 50


class ChartRequest(BaseModel):
    metric: str | None = None
    metric_y: str | None = None
    bins: int = 20
    stage: Literal["raw", "cleaned"] = "cleaned"
    filters: list[FilterClause] = Field(default_factory=list)


class AnomalyRequest(BaseModel):
    ri_version: str | None = None
    stage: Literal["raw", "cleaned"] = "cleaned"
    filters: list[FilterClause] = Field(default_factory=list)


class ReportRequest(BaseModel):
    sections: list[str] = Field(default_factory=lambda: ["stats", "charts", "anomaly"])
