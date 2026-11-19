"""工作台（FR-33、T-26）。

登录后的第一屏必须是**数据**而不是欢迎语：最近数据集 + 它的指标状态摘要 + 全局计数。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Dataset, User
from app.db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.user_id == user.id)) or 0
    rows = db.scalars(
        select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc()).limit(6)
    ).all()

    cards = []
    for row in rows:
        cards.append(
            {
                **row.summary(),
                "health": (row.clean_report or {}).get("health", ""),
                "anomaly_rate": (row.anomaly or {}).get("anomaly_rate"),
            }
        )

    latest = cards[0] if cards else None
    return {
        "username": user.display_name or user.username,
        "dataset_count": int(total),
        "datasets": cards,
        "latest": latest,
        "empty": latest is None,
    }
