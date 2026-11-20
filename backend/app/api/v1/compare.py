"""多数据集并排对比接口（SRS 8.1 ``POST /compare/stats``、FR-29、BR-13）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.dataset import CompareRequest
from app.services import compare as compare_service

router = APIRouter(prefix="/compare", tags=["compare"])


@router.post("/stats")
def compare_stats(
    payload: CompareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """并排描述统计。

    响应里**没有**、也不允许以后有：p 值、置信区间、效应量、"差异显著"之类的字段。
    这个约束写在 BR-13 里，理由写在 ``services/compare.py`` 的模块 docstring 里。
    """
    return compare_service.compare_stats(db, user, payload.dataset_ids, payload.metrics)
