"""v1 路由聚合。新增模块时只改这里一处，``app/main.py`` 不用动。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, dashboard, datasets, reference

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(datasets.router)
api_router.include_router(dashboard.router)
api_router.include_router(reference.router)

__all__ = ["api_router"]
