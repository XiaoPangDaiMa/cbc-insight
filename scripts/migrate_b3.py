"""B3 数据层迁移：三层区间 + 去掉角色（SRS 3.5.1、2.2、FR-24/36/37）。

为什么不用 alembic：本项目至今是 ``create_all()`` + 零迁移的状态，为一次性改动引入
alembic 目录不划算；但这个脚本**必须**可重复执行（先备份、逐项判断已存在则跳过），
因为它会在用户的开发库上跑。

    python scripts/migrate_b3.py                # 迁移 backend/data/app.db
    python scripts/migrate_b3.py --db x.db      # 指定库
    python scripts/migrate_b3.py --dry-run      # 只打印将要执行的语句

做三件事：

1. ``datasets`` 加 ``ri_source`` / ``judged_at`` / ``ranges_snapshot``（BR-18 判定口径快照）。
2. 建 ``user_ranges``（整份保存、只追加、版本号自增）。
3. ``users`` 删 ``role``（v1.6 起无角色；不删会让新代码插入 User 时撞 NOT NULL）。

SQLite 的 ``DROP COLUMN`` 需要 3.35+（Python 3.13 自带 3.4x，满足）。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_DB = BACKEND_DIR / "data" / "app.db"

USER_RANGES_DDL = """
CREATE TABLE IF NOT EXISTS user_ranges (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    user_id VARCHAR(32) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    ranges JSON NOT NULL,
    digest VARCHAR(16) NOT NULL,
    note TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT uq_user_ranges_version UNIQUE (user_id, version)
)
"""

DATASET_COLUMNS = {
    "ri_source": "VARCHAR(48)",
    "judged_at": "DATETIME",
    "ranges_snapshot": "JSON",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def plan(conn: sqlite3.Connection) -> list[str]:
    """返回待执行语句（同时用于 --dry-run 与真实执行，保证两者一致）。"""
    stmts: list[str] = []
    tables = _tables(conn)

    if "datasets" not in tables:
        raise SystemExit("找不到 datasets 表：这个库看起来不是本项目的库")
    existing = _columns(conn, "datasets")
    for name, ddl in DATASET_COLUMNS.items():
        if name not in existing:
            stmts.append(f"ALTER TABLE datasets ADD COLUMN {name} {ddl}")

    if "user_ranges" not in tables:
        stmts.append(USER_RANGES_DDL.strip())

    if "users" in tables and "role" in _columns(conn, "users"):
        # 先把值搬走再删列，属于"先留证据再动手"：万一以后要恢复角色，
        # 至少能从备份文件里查回每人原来的角色
        stmts.append("ALTER TABLE users DROP COLUMN role")

    return stmts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="B3 数据层迁移")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    db_path: Path = args.db
    if not db_path.exists():
        print(f"数据库不存在：{db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        stmts = plan(conn)
        if not stmts:
            print("无需迁移：已经是 B3 结构")
            return 0

        print(f"目标库：{db_path}")
        for stmt in stmts:
            first = stmt.splitlines()[0]
            print(f"  - {first}")
        if args.dry_run:
            print("（dry-run，未执行）")
            return 0

        backup = db_path.with_suffix(f".db.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(db_path, backup)
        print(f"已备份到 {backup.name}")

        for stmt in stmts:
            conn.execute(stmt)
        conn.commit()
        print(f"完成：{len(stmts)} 条语句")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
