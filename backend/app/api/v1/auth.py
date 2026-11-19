"""鉴权接口（SRS 8.1、FR-22 注册登录、FR-34 账号管理）。

几个容易写错、这里刻意写死的点：

* **注册成功直接返回令牌**，前端不用再登录一次（T-27）。
* **用户名大小写不敏感判重**：``Admin`` 撞 ``admin`` → 409/40902（T-27）。
* **锁定以数据库为准**：连续失败 5 次写 ``locked_until``，重启进程也解不开（NFR-S-07、T-30）。
* **对不存在的用户名与密码错误给同样的响应**：否则可以被用来枚举账号。
* **改密吊销该用户全部 refresh token**（T-28）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.deps import get_current_user
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    new_username_key,
    token_fingerprint,
    verify_password,
)
from app.db.models import RefreshToken, User
from app.db.session import get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangeUsernameRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPayload,
    UserPayload,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_payload(user: User) -> UserPayload:
    return UserPayload(
        user_id=user.id,
        username=user.display_name or user.username,
        created_at=user.created_at.isoformat() if user.created_at else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


def _issue_tokens(
    user: User, db: Session, settings: Settings
) -> tuple[str, str]:
    access = create_access_token(user.id, settings)
    refresh, expires = create_refresh_token(user.id, settings)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_fingerprint(refresh),
            expires_at=expires,
        )
    )
    db.commit()
    return access, refresh


def _find_by_username(db: Session, username: str) -> User | None:
    key = new_username_key(username)
    return db.scalar(select(User).where(User.username == key))


@router.post("/register", response_model=TokenPayload, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> TokenPayload:
    try:
        payload.check_confirm()
    except ValueError as exc:
        raise AppError(42201, detail=str(exc)) from exc

    key = new_username_key(payload.username)
    if len(key) < 3:
        raise AppError(42201, detail="用户名至少 3 个字符（不含空白）")
    if _find_by_username(db, key) is not None:
        raise AppError(40902)

    user = User(
        username=key,
        display_name=payload.username,
        password_hash=hash_password(payload.password, settings),
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access, refresh = _issue_tokens(user, db, settings)
    return TokenPayload(
        user_id=user.id,
        username=user.display_name,
        access_token=access,
        refresh_token=refresh,
    )


@router.post("/login", response_model=TokenPayload)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> TokenPayload:
    user = _find_by_username(db, payload.username)

    # 用户不存在时也走一次 bcrypt 校验，避免用响应耗时区分"账号不存在"
    if user is None:
        verify_password(payload.password, "$2b$12$" + "x" * 53)
        raise AppError(40101, detail="用户名或密码错误")

    if user.is_locked:
        raise AppError(42902)

    if not verify_password(payload.password, user.password_hash):
        user.failed_attempts = int(user.failed_attempts or 0) + 1
        if user.failed_attempts >= settings.login_max_failures:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=settings.login_lock_minutes)
            user.failed_attempts = 0
            db.commit()
            raise AppError(42902)
        db.commit()
        raise AppError(40101, detail="用户名或密码错误")

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    db.commit()

    access, refresh = _issue_tokens(user, db, settings)
    return TokenPayload(
        user_id=user.id,
        username=user.display_name,
        access_token=access,
        refresh_token=refresh,
    )


@router.post("/refresh")
def refresh_token(
    payload: RefreshRequest,
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict:
    user_id = decode_token(payload.refresh_token, "refresh", settings)
    stored = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_fingerprint(payload.refresh_token))
    )
    if stored is None or stored.revoked_at is not None or stored.user_id != user_id:
        raise AppError(40101, detail="刷新令牌已失效")
    expires = stored.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        raise AppError(40101, detail="刷新令牌已过期")
    return {"access_token": create_access_token(user_id, settings), "token_type": "bearer"}


@router.post("/logout")
def logout(
    payload: LogoutRequest,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict:
    stored = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_fingerprint(payload.refresh_token))
    )
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserPayload)
def read_me(user: User = Depends(get_current_user)) -> UserPayload:  # noqa: B008
    """用户名与角色**现取**，不从令牌解（T-28）。"""
    return _user_payload(user)


@router.patch("/me", response_model=UserPayload)
def update_username(
    payload: ChangeUsernameRequest,
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> UserPayload:
    key = new_username_key(payload.new_username)
    if len(key) < 3:
        raise AppError(42201, detail="用户名至少 3 个字符（不含空白）")
    if key != user.username and _find_by_username(db, key) is not None:
        raise AppError(40902)
    user.username = key
    user.display_name = payload.new_username
    db.commit()
    db.refresh(user)
    return _user_payload(user)


@router.put("/me/password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict:
    if not verify_password(payload.old_password, user.password_hash):
        raise AppError(40102)
    user.password_hash = hash_password(payload.new_password, settings)
    # 改密后吊销全部 refresh token（T-28）
    now = datetime.now(UTC)
    for token in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)):
        if token.revoked_at is None:
            token.revoked_at = now
    db.commit()
    return {"ok": True}
