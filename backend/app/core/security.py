"""密码哈希与 JWT（SRS NFR-S-02、FR-22、FR-34）。

三条硬约束，改动前先看这里为什么这么写：

1. **JWT 只放 ``sub=user_id``**（外加 ``typ``/``exp``/``jti`` 这类协议字段）。
   不放 username、不放 role——否则改名后令牌里的旧名字会继续生效，
   角色变更也要等到令牌过期，T-28 会直接失败。
2. **refresh token 只以 sha256 存库**。登出、改密时把库里的记录吊销即可，
   不需要维护黑名单。
3. **bcrypt cost 取配置值（默认 12）**，不在代码里写死，测试环境可调低。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import Settings, get_settings
from app.core.errors import AppError

TokenType = Literal["access", "refresh"]


def hash_password(password: str, settings: Settings | None = None) -> str:
    cost = (settings or get_settings()).bcrypt_cost
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=cost)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        # 哈希格式损坏时按"密码不对"处理，不抛 500
        return False


def token_fingerprint(token: str) -> str:
    """refresh token 的库存形式（不可逆）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode(
    user_id: str,
    token_type: TokenType,
    expires_at: datetime,
    settings: Settings,
) -> str:
    payload: dict[str, Any] = {
        "sub": user_id,
        "typ": token_type,
        "jti": uuid.uuid4().hex,
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    return _encode(user_id, "access", expires, settings)


def create_refresh_token(user_id: str, settings: Settings | None = None) -> tuple[str, datetime]:
    """返回 (令牌原文, 过期时刻)。原文只回给客户端，库里存 fingerprint。"""
    settings = settings or get_settings()
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    return _encode(user_id, "refresh", expires, settings), expires


def decode_token(token: str, expected: TokenType, settings: Settings | None = None) -> str:
    """解码并校验令牌类型，返回 ``user_id``。任何异常都归一为 401/40101。"""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AppError(40101, detail="令牌已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise AppError(40101, detail="令牌无效") from exc

    if payload.get("typ") != expected:
        raise AppError(40101, detail=f"需要 {expected} 令牌")
    user_id = payload.get("sub")
    if not user_id:
        raise AppError(40101)
    return str(user_id)


def new_username_key(username: str) -> str:
    """判定重名用的键：去空格 + 小写（FR-34，大小写不敏感）。"""
    return username.strip().lower()


def random_password_suffix() -> str:
    """CLI 重置密码时用，避免出现可猜的默认口令。"""
    return secrets.token_urlsafe(9)
