"""把 SQLite 开发库搬到 Postgres（v1.8 的 5.4 步骤）。

为什么不用"导出 SQL 再导入"：SQLite 的 ``INSERT`` 方言、布尔值（0/1 vs false/true）、
JSON（文本 vs jsonb）三处都不一样，导过去一定会炸在某一行上，而且报错位置毫无意义。

这里用 SQLAlchemy 的 Core 层逐表搬：读出来是 Python 对象（dict / bool / datetime），
写进去由目标方言负责编码。**保留原始主键**——``datasets.id`` 同时是磁盘目录名
（``data/processed/{id}/``）与外键目标，换了 id 等于把所有产物全部孤立。

用法::

    cd backend
    .venv\\Scripts\\python.exe ..\\scripts\\migrate_to_pg.py --dry-run
    .venv\\Scripts\\python.exe ..\\scripts\\migrate_to_pg.py \\
        --source-sqlite data\\app.db \\
        --target postgresql+psycopg://cbc:cbc_dev_password@127.0.0.1:5432/cbc

会先 ``alembic upgrade head`` 建结构，再按依赖顺序搬：users → user_ranges →
reference_snapshots → datasets。``refresh_tokens`` 不搬（旧令牌换库即失效，
用户重新登录即可，搬过去反而留下能用的历史凭证）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db import models  # noqa: E402  注册映射
from app.db.session import run_migrations  # noqa: E402

TABLES = (
    models.User,
    models.UserRanges,
    models.ReferenceSnapshot,
    models.Dataset,
)


def _rows(engine: Engine, model) -> list[dict]:
    with Session(engine) as session:
        return [
            {column.key: getattr(obj, column.key) for column in model.__table__.columns}
            for obj in session.scalars(select(model)).all()
        ]


def _copy(engine: Engine, model, rows: list[dict], *, dry_run: bool) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)
    with engine.begin() as conn:
        conn.execute(model.__table__.insert(), rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite → Postgres 数据搬迁")
    parser.add_argument("--source-sqlite", default=str(BACKEND / "data" / "app.db"))
    parser.add_argument("--target", required=True, help="例如 postgresql+psycopg://cbc:...@127.0.0.1:5432/cbc")
    parser.add_argument("--dry-run", action="store_true", help="只统计行数，不写库")
    parser.add_argument("--truncate", action="store_true", help="先清空目标库同名表（重复执行时用）")
    args = parser.parse_args()

    source_path = Path(args.source_sqlite)
    if not source_path.is_file():
        print(f"找不到 SQLite 文件：{source_path}")
        return 2

    source = create_engine(f"sqlite:///{source_path.as_posix()}")
    target = create_engine(args.target)

    print(f"源：{source_path}（{source_path.stat().st_size / 1024:.0f} KB）")
    print(f"目标：{args.target}")
    if not args.dry_run:
        # run_migrations() 读的是 Settings（环境变量 / backend/.env），所以这里把目标地址
        # 临时注入进程环境——否则会去迁当前配置指向的那个库，静默迁错地方。
        os.environ["CBC_DATABASE_URL"] = args.target
        get_settings.cache_clear()
        run_migrations()
        print("目标库结构已升到 head")

    if args.truncate and not args.dry_run:
        with target.begin() as conn:
            for model in reversed(TABLES):
                conn.execute(text(f'DELETE FROM "{model.__tablename__}"'))
        print("目标库已清空（按依赖反序）")

    total = 0
    for model in TABLES:
        rows = _rows(source, model)
        copied = _copy(target, model, rows, dry_run=args.dry_run)
        total += copied
        print(f"  {model.__tablename__:<20} {copied:>6} 行")

    print(("将搬" if args.dry_run else "已搬") + f" {total} 行")
    if args.dry_run:
        print("（dry-run：未写入任何数据）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
