from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.auth import ROLE_LABEL, ROLES, require_roles
from app.core.e2e import plain_name
from app.core.utils import fmt_dt, next_no
from app.db.database import get_db
from app.db.models import Factory, User

router = APIRouter(prefix="/api/factories", tags=["factories"])

VIEW_ROLES = ROLES
EDIT_ROLES = ROLES
STATUS = {"active": "启用", "disabled": "停用"}


class FactoryIn(BaseModel):
    factory_name: str = Field(min_length=1, max_length=200)
    factory_contact: str = ""
    factory_phone: str = ""
    factory_address: str = ""
    factory_bank: str = ""
    factory_account: str = ""
    remark: str = ""
    status: str = "active"


class FactoryPatch(BaseModel):
    factory_name: Optional[str] = None
    factory_contact: Optional[str] = None
    factory_phone: Optional[str] = None
    factory_address: Optional[str] = None
    factory_bank: Optional[str] = None
    factory_account: Optional[str] = None
    remark: Optional[str] = None
    status: Optional[str] = None


def _can_edit(user: User) -> bool:
    return user.role in EDIT_ROLES


def serialize(row: Factory, user: User) -> dict:
    return {
        "id": row.id,
        "no": row.no,
        "factory_name": row.factory_name,
        "factory_contact": row.factory_contact or "",
        "factory_phone": row.factory_phone or "",
        "factory_address": row.factory_address or "",
        "factory_bank": row.factory_bank or "",
        "factory_account": row.factory_account or "",
        "remark": row.remark or "",
        "status": row.status,
        "status_label": STATUS.get(row.status, row.status),
        "creator_id": row.creator_id,
        "creator_name": row.creator.name if row.creator else "",
        "creator_role": ROLE_LABEL.get(row.creator.role, row.creator.role) if row.creator else "",
        "created_at": fmt_dt(row.created_at),
        "updated_at": fmt_dt(row.updated_at),
        "can_edit": _can_edit(user),
        "can_delete": _can_edit(user),
    }


def _match_q(row: Factory, q: str) -> bool:
    needle = (q or "").strip().lower()
    if not needle:
        return True
    hay = " ".join(
        [
            row.no,
            plain_name(row.factory_name),
            row.factory_contact or "",
            row.factory_phone or "",
            row.factory_address or "",
            plain_name(row.factory_bank),
            row.remark or "",
        ]
    ).lower()
    return needle in hay


def _clean_create(body: FactoryIn) -> dict:
    name = (body.factory_name or "").strip()
    if not name:
        raise HTTPException(400, "请填写工厂名称")
    status = body.status if body.status in STATUS else "active"
    return {
        "factory_name": name,
        "factory_contact": (body.factory_contact or "").strip()[:64],
        "factory_phone": (body.factory_phone or "").strip()[:64],
        "factory_address": (body.factory_address or "").strip()[:200],
        "factory_bank": (body.factory_bank or "").strip(),
        "factory_account": (body.factory_account or "").strip(),
        "remark": (body.remark or "").strip(),
        "status": status,
    }


@router.get("")
def list_factories(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*VIEW_ROLES))],
    q: str = "",
    status: str = "",
):
    rows = (
        db.query(Factory)
        .options(joinedload(Factory.creator))
        .order_by(Factory.id.desc())
        .all()
    )
    if status in STATUS:
        rows = [r for r in rows if r.status == status]
    if q.strip():
        rows = [r for r in rows if _match_q(r, q)]
    return [serialize(r, user) for r in rows]


@router.post("")
def create_factory(
    body: FactoryIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*EDIT_ROLES))],
):
    data = _clean_create(body)
    row = Factory(no=next_no(db, Factory, "GC"), creator_id=user.id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    row = db.query(Factory).options(joinedload(Factory.creator)).filter(Factory.id == row.id).first()
    return serialize(row, user)


@router.patch("/{fid}")
def patch_factory(
    fid: int,
    body: FactoryPatch,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*EDIT_ROLES))],
):
    row = db.query(Factory).options(joinedload(Factory.creator)).filter(Factory.id == fid).first()
    if not row:
        raise HTTPException(404, "工厂不存在")
    payload = body.model_dump(exclude_unset=True)
    if "factory_name" in payload:
        name = (payload["factory_name"] or "").strip()
        if not name:
            raise HTTPException(400, "请填写工厂名称")
        row.factory_name = name
    if "status" in payload and payload["status"] is not None:
        if payload["status"] not in STATUS:
            raise HTTPException(400, "状态无效")
        row.status = payload["status"]
    for key, maxlen in (
        ("factory_contact", 64),
        ("factory_phone", 64),
        ("factory_address", 200),
    ):
        if key in payload and payload[key] is not None:
            setattr(row, key, str(payload[key]).strip()[:maxlen])
    for key in ("factory_bank", "factory_account", "remark"):
        if key in payload and payload[key] is not None:
            setattr(row, key, str(payload[key]).strip())
    db.commit()
    row = db.query(Factory).options(joinedload(Factory.creator)).filter(Factory.id == fid).first()
    return serialize(row, user)


@router.delete("/{fid}")
def delete_factory(
    fid: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*EDIT_ROLES))],
):
    row = db.query(Factory).filter(Factory.id == fid).first()
    if not row:
        raise HTTPException(404, "工厂不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
