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
    # pre_ping：连接被掐断后自动重连。WSL 里的 Postgres 会随宿主休眠掉线，
    # 没有它时第一个请求必然 500，报错还只是"服务器意外关闭连接"——很难往这里想。
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # SQLite 默认禁止跨线程复用连接，而 FastAPI 的同步端点跑在线程池里
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # 连接池上限按"单机一个学生 + 几个后台脚本"取，不是按线上并发调
        kwargs.update({"pool_size": 5, "max_overflow": 5, "pool_recycle": 1800})
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


def run_migrations(settings: Settings | None = None) -> None:
    """把库升到最新迁移（v1.8 起，Postgres 路径必须走这里）。

    为什么不再用 ``create_all``：它只会"补齐缺的表"，不会改列、不会删列、也不会
    在新旧结构之间做任何转换。开发期删库重建没关系，一旦库里有了账号和数据集，
    改一个列就只剩"手写 SQL"这一条路，而手写 SQL 没有记录、没法回退。
    """
    from alembic.config import Config

    from alembic import command

    settings = settings or get_settings()
    config = Config(str(settings.backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(settings.backend_dir / "alembic"))
    command.upgrade(config, "head")


def init_db(settings: Settings | None = None) -> None:
    """建表 / 升级结构。

    * SQLite（默认，零依赖起步）：仍用 ``create_all``，因为它就是临时开发库。
    * Postgres（生产路径）：跑 alembic 迁移，失败即启动失败——
      "结构不对还硬启动"比启动不了更难查。
    """
    from app.db.base import Base

    settings = settings or get_settings()
    settings.ensure_dirs()
    if settings.database_url.startswith("sqlite"):
        from app.db import models  # noqa: F401  注册映射

        Base.metadata.create_all(get_engine(settings))
        return
    run_migrations(settings)


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
