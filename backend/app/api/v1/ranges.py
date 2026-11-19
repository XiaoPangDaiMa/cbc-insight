"""我的参考区间（SRS 8.1、FR-24 / FR-36 / FR-37、3.5.1 三层模型）。

三条与"看起来更省事"的写法相反的决定：

* **PUT 整份替换、版本号自增、理由必填**（3.5.1）。逐条改会让"我改过哪些"随默认表升级
  而失真；不写理由的改动一个月后自己都不认。
* **不提供"把某人的区间共享给别人"**（2.2 用户与可见性边界）：区间是个人口径，
  共享会让"同一份数据两个人看到不同结论"变成默认行为。
* **临时试算没有保存端点**（FR-37）：它只活在图表请求里，前端拖完不落库。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.dataset import TempRangesRequest
from app.services import ranges_service

router = APIRouter(prefix="/me/reference-ranges", tags=["reference"])


def _payload(db: Session, user: User) -> dict[str, Any]:
    default = ranges_service.default_effective()
    mine = ranges_service.user_effective(db, user)
    return {
        "default": {
            "source": default.source,
            "version": default.version,
            "digest": default.digest,
            "items": ranges_service.items_of(default.ranges),
        },
        "mine": (
            {
                "source": mine.source,
                "version": mine.version,
                "digest": mine.digest,
                "note": mine.note,
                "items": ranges_service.items_of(mine.ranges),
            }
            if mine
            else None
        ),
        "effective": (mine or default).to_payload(),
        "metrics": list(ranges_service.RANGE_METRICS),
    }


@router.get("")
def read_mine(
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """默认表 + 我的区间 + 当前生效口径，一次给全（前端一个请求就能画完整页）。"""
    return _payload(db, user)


@router.put("")
def put_mine(
    payload: dict[str, Any],
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """整份保存。``{"ranges": {...15 项...}, "note": "按本院检验科区间调整"}``。"""
    ranges = payload.get("ranges")
    note = str(payload.get("note") or "")
    row = ranges_service.save(db, user, ranges or {}, note)
    return {
        "ok": True,
        "version": row.version,
        "digest": row.digest,
        "saved_at": row.created_at.isoformat() if row.created_at else None,
        "state": _payload(db, user),
    }


@router.post("/reset")
def reset_mine(
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    ranges_service.reset(db, user)
    return {"ok": True, "state": _payload(db, user)}


@router.get("/versions")
def list_mine_versions(
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    return {"items": ranges_service.versions(db, user)}


@router.post("/preview")
def preview_temp(
    payload: TempRangesRequest,
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """试算口径回显：只算 digest 与来源，不碰任何数据（FR-37）。"""
    eff = ranges_service.build_temp(db, user, payload.temp_ranges)
    return {"effective": eff.to_payload()}
