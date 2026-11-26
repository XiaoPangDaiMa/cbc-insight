"""Alembic 环境（v1.8 起）。

要点：
* URL 从 ``app.core.config.get_settings()`` 读，不写死在 alembic.ini 里——
  同一份迁移必须既能跑在 WSL 的 Postgres 上，也能跑在集成测试的临时库上。
* ``target_metadata`` 指向项目模型，autogenerate 才能看到真实结构。
* ``compare_type=True``：SQLite 时代改列类型不会报错也不会生效，开了它才在
  生成迁移时把类型变化算进 diff（例如 String(64) → String(128)）。
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db import models  # noqa: F401  必须导入，模型才会注册到 metadata
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False 是必须的（v1.8 的踩坑记录）：
    # 后端启动时会先跑一次 ``alembic upgrade head``（db/session.py::run_migrations），
    # 而 ``fileConfig`` 默认会把"已存在的 logger"全部关掉——uvicorn 的
    # ``Application startup complete.`` 与 ``Uvicorn running on ...`` 正好是
    # 那之后才打印的，于是控制台看起来"卡在 alembic 那两行不动"，
    # 其实服务早就正常起来了（端口在听、/healthz 返回 200），只是这行日志被吞了。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
