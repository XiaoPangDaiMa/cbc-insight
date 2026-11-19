"""SQLAlchemy 声明式基类。

单独一个模块是为了让 ``models`` 与 ``session`` 之间不出现循环导入，
alembic 的 env.py 也只需要 import 这一个对象来做 autogenerate。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
