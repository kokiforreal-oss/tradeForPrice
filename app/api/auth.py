from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import ROLE_LABEL, ROLES, create_token, get_current_user, hash_password, require_roles, verify_password
from app.db.database import get_db
from app.db.models import User
from app.core.utils import fmt_dt

router = APIRouter(prefix="/api", tags=["auth-users"])


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    name: str
    role: str


class UserPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "role": u.role,
        "role_label": ROLE_LABEL.get(u.role, u.role),
        "is_active": u.is_active,
        "created_at": fmt_dt(u.created_at),
    }


@router.post("/auth/login")
def login(body: LoginIn, db: Annotated[Session, Depends(get_db)]):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(400, "账号已停用")
    return {"token": create_token(user), "user": user_out(user)}


@router.get("/auth/me")
def me(user: Annotated[User, Depends(get_current_user)]):
    return user_out(user)


@router.get("/users")
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    rows = db.query(User).order_by(User.id.asc()).all()
    return [user_out(u) for u in rows]


@router.post("/users")
def create_user(
    body: UserIn,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    if body.role not in ROLES:
        raise HTTPException(400, "角色无效")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "用户名已存在")
    u = User(
        username=body.username,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return user_out(u)


@router.patch("/users/{user_id}")
def patch_user(
    user_id: int,
    body: UserPatch,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[User, Depends(require_roles("admin"))],
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(400, "角色无效")
        u.role = body.role
    if body.name is not None:
        u.name = body.name
    if body.is_active is not None:
        if u.id == current.id and not body.is_active:
            raise HTTPException(400, "不能停用自己")
        u.is_active = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(u)
    return user_out(u)
