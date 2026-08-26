from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import User

bearer = HTTPBearer(auto_error=False)

ROLES = ("admin", "sales", "purchase", "finance")
ROLE_LABEL = {
    "admin": "管理员",
    "sales": "销售",
    "purchase": "采购",
    "finance": "财务",
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.access_token_expire_hours),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def get_current_user(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    try:
        data = jwt.decode(creds.credentials, settings.secret_key, algorithms=["HS256"])
        user_id = int(data["sub"])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不可用")
    return user


def require_roles(*roles: str):
    def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role in roles:
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN, "没有权限执行此操作")

    return checker
