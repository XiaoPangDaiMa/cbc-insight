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


class CompareRequest(BaseModel):
    """POST /compare/stats（FR-29 多数据集并排对比）。

    数量上限写在这里而不是靠前端限制：接口是公开契约，能被 curl 直接调用，
    所以"最多 4 个"必须由服务端拒绝（BR-13 之外的第二条护栏）。
    """

    dataset_ids: list[str] = Field(min_length=2, max_length=4)
    metrics: list[str] | None = None


class ChartRequest(BaseModel):
    metric: str | None = None
    metric_y: str | None = None
    bins: int = 20
    stage: Literal["raw", "cleaned"] = "cleaned"
    filters: list[FilterClause] = Field(default_factory=list)
    #: 临时试算区间（FR-37）：``{"hgb": {"low": 120, "high": 170}}``，
    #: 可带 ``female_low`` / ``female_high``。只在这次请求里生效，**不落库、不进导出**。
    temp_ranges: dict[str, dict[str, float | None]] | None = None


class RejudgeRequest(BaseModel):
    """POST /datasets/{id}/rejudge（9.2）：用**已保存的**区间重放 S6–S7。

    刻意不接临时区间：临时层只活在图表请求里，一旦让它写进产物，
    "我看到的"和"报告里的"就会分叉（RK-26）。
    """

    note: str | None = None


class TempRangesRequest(BaseModel):
    """临时试算区间（FR-37）：只在这次请求/预览里生效，不落库。"""

    temp_ranges: dict[str, dict[str, float | None]] = Field(default_factory=dict)


class AnomalyRequest(BaseModel):
    ri_version: str | None = None
    stage: Literal["raw", "cleaned"] = "cleaned"
    filters: list[FilterClause] = Field(default_factory=list)


class ReportRequest(BaseModel):
    sections: list[str] = Field(default_factory=lambda: ["stats", "charts", "anomaly"])
