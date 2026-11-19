"""FastAPI 应用入口（SRS 7.4）。

错误响应统一走 8.3 的 ``{"code", "message", "hint", "detail", "trace_id"}``：
前端按 ``code`` 分支，绝不按文案匹配。未捕获异常一律 50001 并带 ``trace_id``，
让"计算异常"至少能被定位（而不是白屏）。
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import init_db

logger = logging.getLogger("cbc")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="血常规数据分析与可视化系统",
        version="0.1.0",
        description="CBC Insight：脱敏血常规数据的队列级分析与可视化（SRS CBC-INSIGHT-SRS-001）",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Export-Meta", "X-Export-Filename"],
    )

    @application.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @application.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": 42201,
                "message": "参数校验失败",
                "hint": "请检查标红字段",
                "detail": exc.errors(),
            },
        )

    @application.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        trace_id = uuid.uuid4().hex[:12]
        logger.exception("unhandled error trace_id=%s", trace_id)
        return JSONResponse(
            status_code=500,
            content={
                "code": 50001,
                "message": "计算异常",
                "hint": "请记录 trace_id 后反馈",
                "detail": str(exc)[:300],
                "trace_id": trace_id,
            },
        )

    @application.get("/healthz", tags=["meta"])
    def healthz() -> dict:
        return {"ok": True, "version": application.version}

    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
