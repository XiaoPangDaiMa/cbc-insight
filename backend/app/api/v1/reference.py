"""默认参考区间（SRS 3.5、附录 A）。

v1.6 起**没有"管理员统一改区间"这回事**：默认表随代码发布（``resources/reference_ranges.yaml``），
只读；用户自己的口径在 ``/me/reference-ranges``（``app/api/v1/ranges.py``）。
这里保留的只是"看看默认表长什么样"+ 历史快照列表，方便对照"我的区间改了哪些项"。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReferenceSnapshot
from app.db.session import get_db
from app.services import ranges_service

router = APIRouter(prefix="/reference-ranges", tags=["reference"])


@router.get("")
def list_default() -> dict[str, Any]:
    ranges = ranges_service.default_effective()
    return {
        "version": ranges.version,
        "source": ranges.source,
        "digest": ranges.digest,
        "ranges": list(ranges_service.items_of(ranges.ranges).values()),
    }


@router.get("/snapshots")
def list_snapshots(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    rows = db.scalars(select(ReferenceSnapshot).order_by(ReferenceSnapshot.created_at.desc())).all()
    return {
        "items": [
            {
                "version": row.version,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }
