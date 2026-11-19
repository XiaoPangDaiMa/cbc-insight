"""FastAPI 依赖：当前用户与数据集的归属校验（FR-22、FR-28、NFR-S-03）。

**越权一律返回 40401 而不是 40301**：403 等于告诉对方"这个 id 存在，只是不属于你"，
可以拿来枚举他人数据集。

v1.6 起**没有角色**（2.2「用户与可见性边界」）：每个账号只看得到自己的数据，
不存在"管理员能看全站"这回事，因此这里也不再提供 ``require_admin``。
"""

from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decode_token
from app.db.models import Dataset, User
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError(40101, detail="缺少访问令牌")
    user_id = decode_token(credentials.credentials, "access")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(40101, detail="用户不存在或已停用")
    return user


def get_owned_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != user.id:
        raise AppError(40401)
    return dataset
