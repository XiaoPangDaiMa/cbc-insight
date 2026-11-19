"""数据库会话（SRS 7.2 FastAPI + SQLAlchemy、7.5 存储分工）。

默认 ``sqlite:///data/app.db`` 是为了"clone 下来就能跑"；生产/集成测试用
``CBC_DATABASE_URL=postgresql+psycopg://...`` 切到 Postgres（10.3 的 ``-m integration``）。
两者共用同一套模型，因此测试里跑过的 SQL 与线上一致。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def build_engine(settings: Settings) -> Engine:
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # SQLite 默认禁止跨线程复用连接，而 FastAPI 的同步端点跑在线程池里
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine(settings or get_settings())
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _factory
    if _factory is None:
        _factory = sessionmaker(bind=get_engine(settings), autoflush=False, expire_on_commit=False)
    return _factory


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话，请求结束即关闭。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db(settings: Settings | None = None) -> None:
    """建表。

    MVP 阶段用 ``create_all`` 起步，alembic 迁移在 M4 补齐；这里的 import 是延迟的，
    因为 models 依赖 Base 而已，但仍然避免在模块导入期就建连接。
    """
    from app.db import models  # noqa: F401  注册映射
    from app.db.base import Base

    settings = settings or get_settings()
    settings.ensure_dirs()
    Base.metadata.create_all(get_engine(settings))


def ping() -> bool:
    """集成测试的"先 ping 再跑"（10.3 硬约束 1）。连不上直接抛，不静默跳过。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("请先 docker compose up -d db redis（数据库未就绪）") from exc


def reset_engine() -> None:
    """测试切换数据库 URL 时用。"""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None
