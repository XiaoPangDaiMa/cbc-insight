"""Postgres 方言的差异点（``-m integration``，只在真库上跑）。

SQLite 太宽容，下面四件事在它上面**永远不会暴露**，却会在切库当天一起爆：

1. ``varchar(n)`` 真的拒收超长字符串（SQLite 不看长度）；
2. ``jsonb`` 拒收 ``NaN``（SQLite 把它当普通文本存下来）；
3. ``boolean`` 是真类型（SQLite 存 0/1，读回来靠转换）；
4. ``timestamptz`` 读回来带时区（SQLite 丢掉时区，比较时容易错 8 小时）。

这些用例**只写自己造的行、结束时按 id 删掉**，不做 TRUNCATE：第一版用了
``TRUNCATE datasets CASCADE``，把开发库里刚搬过来的 11 个数据集全清了——
集成测试跑在真库上时，任何"整表清理"都是不可接受的副作用。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DataError, DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.jsonsafe import sanitize_json
from app.db import models
from app.db.session import get_engine, reset_engine, run_migrations

pytestmark = pytest.mark.integration

CREATED_DATASETS = ("pg-json-bad", "pg-json-ok", "pg-len-bad", "pg-bool-ok")
USER_ID = "pg-user-dialect"


@pytest.fixture(scope="module", autouse=True)
def _require_postgres():
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        pytest.skip(f"需要 Postgres：当前 CBC_DATABASE_URL={settings.database_url[:24]}…")
    reset_engine()
    run_migrations(settings)
    yield
    # 收尾：只删自己造的行
    with Session(get_engine()) as session:
        session.execute(delete(models.Dataset).where(models.Dataset.id.in_(CREATED_DATASETS)))
        session.execute(delete(models.User).where(models.User.id == USER_ID))
        session.commit()


@pytest.fixture()
def user_id() -> str:
    """datasets 有外键，先造一个满足约束的账号。"""
    with Session(get_engine()) as session:
        if session.get(models.User, USER_ID) is None:
            session.add(
                models.User(
                    id=USER_ID,
                    username="pg_dialect_user",
                    display_name="PG 方言测试",
                    password_hash="x",
                )
            )
            session.commit()
    return USER_ID


def _dataset(dataset_id: str, user_id: str, **kwargs) -> models.Dataset:
    payload = {
        "id": dataset_id,
        "user_id": user_id,
        "name": "方言测试",
        "original_filename": "a.csv",
        # 同一用户的 sha256 有唯一约束：每个用例用自己的哈希，否则第二个插入就撞 409 语义
        "sha256": hashlib.sha256(dataset_id.encode()).hexdigest(),
    }
    payload.update(kwargs)
    return models.Dataset(**payload)


def test_jsonb_rejects_nan_and_accepts_sanitized_payload(user_id: str) -> None:
    """入库前必须 sanitize：NaN 在 jsonb 上是硬错误，不是"显示成 null"。"""
    engine = get_engine()

    with pytest.raises((DBAPIError, DataError)), Session(engine) as session:
        session.add(_dataset("pg-json-bad", user_id, stats={"mean": float("nan")}))
        session.commit()

    with Session(engine) as session:
        session.add(
            _dataset(
                "pg-json-ok",
                user_id,
                stats=sanitize_json({"mean": float("nan"), "note": "血红蛋白"}),
            )
        )
        session.commit()
        loaded = session.get(models.Dataset, "pg-json-ok")
        assert loaded is not None
        assert loaded.stats["note"] == "血红蛋白"
        assert loaded.stats["mean"] is None


def test_varchar_length_is_enforced(user_id: str) -> None:
    """Postgres 会真的拒收超长；代码里的截断不是防御性冗余，是必需。"""
    with pytest.raises((DBAPIError, DataError)), Session(get_engine()) as session:
        session.add(_dataset("pg-len-bad", user_id, original_filename="x" * 300))
        session.commit()


def test_boolean_and_timestamptz_roundtrip(user_id: str) -> None:
    engine = get_engine()
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(_dataset("pg-bool-ok", user_id, unified_ranges=True, judged_at=now))
        session.commit()

    with Session(engine) as session:
        loaded = session.get(models.Dataset, "pg-bool-ok")
        assert loaded is not None
        assert loaded.unified_ranges is True
        assert loaded.judged_at is not None
        # 读回来必须带时区：否则前端显示差 8 小时，"最新一次判定"也会排错序
        assert loaded.judged_at.tzinfo is not None
        assert abs(loaded.judged_at - now) < timedelta(seconds=2)


def test_schema_is_at_head() -> None:
    """迁移记录存在（alembic_version 有且只有一行）。"""
    with get_engine().connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM alembic_version")).scalar_one()
    assert count == 1
