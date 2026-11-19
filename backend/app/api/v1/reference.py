"""参考区间管理（SRS 8.1、FR-24）。

区间外置的理由见 7.3 决策 7：不同实验室、不同检测系统的区间不同，换版本不该改代码。
写入时**同时落库快照**——历史报告要能按当时的 ``ri_version`` 复现。
"""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.deps import require_admin
from app.core.errors import AppError
from app.db.models import ReferenceSnapshot, User
from app.db.session import get_db
from app.services.loader import load_reference_ranges, reset_caches

router = APIRouter(prefix="/reference-ranges", tags=["reference"])


@router.get("")
def list_ranges() -> dict[str, Any]:
    ranges = load_reference_ranges()
    items = []
    for metric, interval in ranges.default.items():
        items.append(
            {
                "metric": metric,
                "unit": interval.unit,
                "low": interval.low,
                "high": interval.high,
                "gender": interval.gender or "all",
                "source": interval.source,
            }
        )
    return {
        "version": ranges.version,
        "source": ranges.source,
        "note": ranges.note,
        "ranges": items,
    }


@router.put("")
def update_ranges(
    payload: dict[str, Any],
    db: Session = Depends(get_db),  # noqa: B008
    _: User = Depends(require_admin),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    """整份替换区间表。

    刻意做成"整份替换"而不是"逐条改"：逐条改会让不同指标的版本号错位，
    报告里记一个 ``ri_version`` 却对应半新半旧的表，比不记还糟。
    """
    version = str(payload.get("version") or "").strip()
    ranges = payload.get("ranges")
    if not version:
        raise AppError(42201, detail="缺少 version（如 2026.11.2）")
    if not isinstance(ranges, dict) or not ranges:
        raise AppError(42201, detail="ranges 必须是非空对象")

    current = load_reference_ranges()
    if version == current.version:
        raise AppError(42201, detail=f"版本号 {version} 已存在，请递增版本号")

    content = {"version": version, "source": payload.get("source", current.source), "ranges": ranges}
    target = (settings.resources_dir / "reference_ranges.yaml")
    if target.exists():
        backup = target.with_suffix(".yaml.bak")
        backup.write_bytes(target.read_bytes())
    target.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8")
    reset_caches()

    existing = db.scalar(select(ReferenceSnapshot).where(ReferenceSnapshot.version == version))
    if existing is None:
        db.add(ReferenceSnapshot(version=version, content=content))
        db.commit()
    return {"new_version": version}


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
