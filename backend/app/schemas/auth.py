"""鉴权相关请求/响应模型（SRS 8.1、FR-22/34）。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

USERNAME_MIN = 3
USERNAME_MAX = 32
PASSWORD_MIN = 8
PASSWORD_MAX = 64


class RegisterRequest(BaseModel):
    username: str = Field(min_length=USERNAME_MIN, max_length=USERNAME_MAX)
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    password_confirm: str | None = None

    @field_validator("username")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("用户名不能为空白")
        return value

    def check_confirm(self) -> None:
        if self.password_confirm is not None and self.password_confirm != self.password:
            raise ValueError("两次输入的密码不一致")


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ChangeUsernameRequest(BaseModel):
    new_username: str = Field(min_length=USERNAME_MIN, max_length=USERNAME_MAX)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class UserPayload(BaseModel):
    user_id: str
    username: str
    created_at: str | None = None
    last_login_at: str | None = None


class TokenPayload(BaseModel):
    user_id: str
    username: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
