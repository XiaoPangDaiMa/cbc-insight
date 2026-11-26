"""数据模型（SRS 7.5 计算与存储的分工、FR-22/28/34）。

设计要点：

* **用户**只存 ``password_hash``，永不存明文；``username`` 以小写形式存并加唯一索引，
  这样 ``Admin`` 与 ``admin`` 被判为同一个账号（FR-34、T-27），而 ``display_name``
  保留用户输入的大小写用于展示。
* **数据集**把每一步管线的产物路径与摘要 JSON 一起存下来（SRS 9：每步必须落盘）。
  统计、图表都从这里读，而不是每次重新算——这既是性能要求（NFR-P-01），
  也是"报告要能复现当时结果"的前提（7.3 决策 7）。
* **refresh token** 存哈希而不是原文：泄露数据库也拿不到可用令牌（NFR-S-02）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Postgres 上用 jsonb（可建 GIN 索引、能查键值），SQLite 上仍是普通 json。
# 声明成变量而不是在每个列上写 with_variant，是为了让"哪些列是 JSON"一眼可见。
JSONColumn = JSON().with_variant(JSONB, "postgresql")


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    #: 连续失败次数与锁定截止时刻（NFR-S-07）。**锁定以数据库为准**，
    #: 不放在内存里——否则重启即可绕过。
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    datasets: Mapped[list[Dataset]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def is_locked(self) -> bool:
        if self.locked_until is None:
            return False
        locked_until = self.locked_until
        if locked_until.tzinfo is None:  # SQLite 读回来是 naive
            locked_until = locked_until.replace(tzinfo=UTC)
        return locked_until > utcnow()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256(原文)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReferenceSnapshot(Base):
    """参考区间配置的只读快照（7.3 决策 7：历史报告要能复现）。"""

    __tablename__ = "reference_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    content: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserRanges(Base):
    """用户自有的参考区间（SRS 3.5.1 三层模型的「我的区间」层）。

    三条刻意的设计（3.5.1 四条硬性语义）：

    * **每次保存是整份 16 项**，不是差异。差异存储会让"改了哪几项"随默认值升级而失真。
    * **只追加不修改**：每次保存写一行新版本，``version`` 自增；历史版本保留，
      这样才能回答"我上次把 HGB 下限定成多少"。
    * **``note`` 必填**：改标准是有判断在里面的事，写不出理由的改动一个月后自己都不认。
    """

    __tablename__ = "user_ranges"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_user_ranges_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    ranges: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    digest: Mapped[str] = mapped_column(String(16), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        # 同一用户重复上传同一文件 → 409/40901（T-17），因此哈希在用户内唯一
        UniqueConstraint("user_id", "sha256", name="uq_datasets_user_sha"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(128))
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    rows: Mapped[int] = mapped_column(Integer, default=0)
    columns: Mapped[int] = mapped_column(Integer, default=0)
    #: uploaded → cleaned → failed（S1–S6 由上传流程自动串联，9.1）
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    ri_version: Mapped[str] = mapped_column(String(32), default="")
    #: 判定口径标识：``default@2026.11.1`` / ``user#v5`` / ``unified@…``（3.5.1 口径标识表）
    ri_source: Mapped[str] = mapped_column(String(48), default="")
    #: 最近一次判定的时刻。改区间不会自动重判（BR-18），界面靠它判断"陈旧"
    judged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 判定当时生效区间的整份快照（3.5.1：判定即快照，16 项 + 口径 + digest）
    ranges_snapshot: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    #: FR-16 的唯一例外：数据集无 gender 列、用户上传时**显式勾选**按统一区间判定。
    #: 默认 False（BR-17：性别缺失一律判 NA，系统不替用户猜）。
    unified_ranges: Mapped[bool] = mapped_column(Boolean, default=False)

    #: 管线产物（9：每步必须落盘）。键名见 :mod:`app.services.pipeline_runner`
    artifacts: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    mapping: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    quality: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    clean_report: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    stats: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    anomaly: Mapped[dict] = mapped_column(JSONColumn, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="datasets")

    def summary(self) -> dict:
        return {
            "dataset_id": self.id,
            "name": self.name,
            "original_filename": self.original_filename,
            "rows": self.rows,
            "columns": self.columns,
            "status": self.status,
            "ri_version": self.ri_version,
            "ri_source": self.ri_source,
            "judged_at": self.judged_at.isoformat() if self.judged_at else None,
            "unified_ranges": bool(self.unified_ranges),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
