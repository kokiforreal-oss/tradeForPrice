from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.auth import ROLE_LABEL, ROLES, require_roles
from app.core.e2e import plain_name
from app.core.utils import fmt_dt, next_no
from app.db.database import get_db
from app.db.models import Customer, User

router = APIRouter(prefix="/api/customers", tags=["customers"])

VIEW_ROLES = ROLES
EDIT_ROLES = ROLES
STATUS = {"active": "启用", "disabled": "停用"}
CURRENCIES = ("RMB", "USD", "EUR")


class CustomerIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    country: str = ""
    contact_name: str = ""
    phone: str = ""
    email: str = ""
    currency: str = "RMB"
    address: str = ""
    remark: str = ""
    status: str = "active"


class CustomerPatch(BaseModel):
    customer_name: Optional[str] = None
    country: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    currency: Optional[str] = None
    address: Optional[str] = None
    remark: Optional[str] = None
    status: Optional[str] = None


def _can_edit(user: User) -> bool:
    return user.role in EDIT_ROLES


def serialize(row: Customer, user: User) -> dict:
    return {
        "id": row.id,
        "no": row.no,
        "customer_name": row.customer_name,
        "country": row.country or "",
        "contact_name": row.contact_name or "",
        "phone": row.phone or "",
        "email": row.email or "",
        "currency": row.currency or "RMB",
        "address": row.address or "",
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


def _match_q(row: Customer, q: str) -> bool:
    needle = (q or "").strip().lower()
    if not needle:
        return True
    hay = " ".join(
        [
            row.no,
            plain_name(row.customer_name),
            row.country or "",
            row.contact_name or "",
            row.phone or "",
            row.email or "",
            row.address or "",
            row.remark or "",
        ]
    ).lower()
    return needle in hay


def _clean_create(body: CustomerIn) -> dict:
    name = (body.customer_name or "").strip()
    if not name:
        raise HTTPException(400, "请填写客户名称")
    currency = (body.currency or "RMB").strip().upper()
    if currency not in CURRENCIES:
        raise HTTPException(400, "币种仅为 RMB / USD / EUR")
    status = body.status if body.status in STATUS else "active"
    return {
        "customer_name": name,
        "country": (body.country or "").strip()[:64],
        "contact_name": (body.contact_name or "").strip()[:64],
        "phone": (body.phone or "").strip()[:64],
        "email": (body.email or "").strip()[:128],
        "currency": currency,
        "address": (body.address or "").strip()[:200],
        "remark": (body.remark or "").strip(),
        "status": status,
    }


@router.get("")
def list_customers(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*VIEW_ROLES))],
    q: str = "",
    status: str = "",
):
    rows = (
        db.query(Customer)
        .options(joinedload(Customer.creator))
        .order_by(Customer.id.desc())
        .all()
    )
    if status in STATUS:
        rows = [r for r in rows if r.status == status]
    if q.strip():
        rows = [r for r in rows if _match_q(r, q)]
    return [serialize(r, user) for r in rows]


@router.post("")
def create_customer(
    body: CustomerIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*EDIT_ROLES))],
):
    data = _clean_create(body)
    row = Customer(no=next_no(db, Customer, "KH"), creator_id=user.id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    row = db.query(Customer).options(joinedload(Customer.creator)).filter(Customer.id == row.id).first()
    return serialize(row, user)


@router.patch("/{cid}")
def patch_customer(
    cid: int,
    body: CustomerPatch,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*EDIT_ROLES))],
):
    row = db.query(Customer).options(joinedload(Customer.creator)).filter(Customer.id == cid).first()
    if not row:
        raise HTTPException(404, "客户不存在")
    payload = body.model_dump(exclude_unset=True)
    if "customer_name" in payload:
        name = (payload["customer_name"] or "").strip()
        if not name:
            raise HTTPException(400, "请填写客户名称")
        row.customer_name = name
    if "currency" in payload and payload["currency"] is not None:
        currency = str(payload["currency"]).strip().upper()
        if currency not in CURRENCIES:
            raise HTTPException(400, "币种仅为 RMB / USD / EUR")
        row.currency = currency
    if "status" in payload and payload["status"] is not None:
        if payload["status"] not in STATUS:
            raise HTTPException(400, "状态无效")
        row.status = payload["status"]
    for key, maxlen in (
        ("country", 64),
        ("contact_name", 64),
        ("phone", 64),
        ("email", 128),
        ("address", 200),
    ):
        if key in payload and payload[key] is not None:
            setattr(row, key, str(payload[key]).strip()[:maxlen])
    if "remark" in payload and payload["remark"] is not None:
        row.remark = str(payload["remark"]).strip()
    db.commit()
    row = db.query(Customer).options(joinedload(Customer.creator)).filter(Customer.id == cid).first()
    return serialize(row, user)


@router.delete("/{cid}")
def delete_customer(
    cid: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(*EDIT_ROLES))],
):
    row = db.query(Customer).filter(Customer.id == cid).first()
    if not row:
        raise HTTPException(404, "客户不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
