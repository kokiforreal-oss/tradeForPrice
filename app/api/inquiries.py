from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.access import can_view_inquiry, can_view_order, filter_inquiries
from app.core.auth import get_current_user, require_roles
from app.db.database import get_db
from app.db.models import Inquiry, InquiryLine, Order, OrderLog, Product, Quote, QuoteLine, User, utcnow
from app.core.e2e import MoneyIn, money
from app.core.utils import fmt_dt, next_no, to_float

router = APIRouter(prefix="/api/inquiries", tags=["inquiries"])

INQ_STATUS = {
    "pending_quote": "待报价",
    "quoted": "已报价",
    "selling": "销售中",
    "won": "已完成",
    "closed": "已完成",
}
DONE_STATUSES = ("won", "closed")


def inquiry_status_label(inq: Inquiry) -> str:
    if inq.order or inq.status in DONE_STATUSES:
        return "已完成"
    return INQ_STATUS.get(inq.status, inq.status)

CLOSE_REASONS = ("客户未回复", "客户长时间未回", "价格不接受", "客户取消", "其他")


class LineIn(BaseModel):
    product_id: Optional[int] = None
    product_name: str = ""
    spec: str = ""
    unit: str = "pcs"
    quantity: float = Field(gt=0)
    target_price: Optional[MoneyIn] = None
    remark: str = ""


class InquiryIn(BaseModel):
    customer_name: str
    contact_name: str = ""
    phone: str = ""
    email: str = ""
    currency: str = "RMB"
    requirement: str = ""
    lines: List[LineIn]


class QuoteLineIn(BaseModel):
    inquiry_line_id: int
    unit_price: MoneyIn = 0


class QuoteIn(BaseModel):
    note: str = ""
    lead_days: int = 0
    lines: List[QuoteLineIn]


class SelectIn(BaseModel):
    quote_id: int


class RequoteIn(BaseModel):
    reason: str = Field(min_length=1, description="二次询价原因")


class CloseIn(BaseModel):
    reason: str = Field(min_length=1, description="结束原因分类")
    detail: str = ""


def make_inquiry_line(db: Session, inquiry_id: int, ln: LineIn) -> InquiryLine:
    p = db.get(Product, ln.product_id) if ln.product_id else None
    if ln.product_id and (not p or p.status != "active"):
        raise HTTPException(400, "产品不存在或已停用")
    name = (ln.product_name or "").strip() or (p.name if p else "")
    if not name:
        raise HTTPException(400, "请选择产品或手动填写产品名称")
    return InquiryLine(
        inquiry_id=inquiry_id,
        product_id=p.id if p else None,
        product_name=name,
        spec=(ln.spec or "").strip() or (p.spec if p else "") or "",
        unit=(ln.unit or "").strip() or (p.unit if p else "") or "pcs",
        quantity=money(ln.quantity),
        target_price=money(ln.target_price) if ln.target_price is not None else None,
        remark=ln.remark,
    )


def parse_requote_log(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def compose_close_reason(body: CloseIn) -> str:
    reason = (body.reason or "").strip()
    detail = (body.detail or "").strip()
    if reason not in CLOSE_REASONS:
        raise HTTPException(400, "请选择有效的结束原因")
    if reason == "其他":
        if not detail:
            raise HTTPException(400, "选择「其他」时请填写具体原因")
        return f"其他：{detail}"
    if detail:
        return f"{reason}（{detail}）"
    return reason


def can_view(user: User, inq: Inquiry) -> bool:
    return can_view_inquiry(user, inq)


def serialize_inquiry(inq: Inquiry, user: User) -> dict:
    show_cost = user.role in ("admin", "purchase")
    lines = []
    for ln in inq.lines:
        p = ln.product
        lines.append(
            {
                "id": ln.id,
                "product_id": ln.product_id,
                "sku": p.sku if p else "",
                "product_name": (p.name if p else "") or ln.product_name or "",
                "spec": (p.spec if p else "") or ln.spec or "",
                "unit": (p.unit if p else "") or ln.unit or "pcs",
                "cost_price": to_float(p.cost_price) if p and show_cost else None,
                "quantity": to_float(ln.quantity),
                "target_price": to_float(ln.target_price),
                "remark": ln.remark,
            }
        )
    quotes = []
    for q in inq.quotes:
        qlines = []
        for ql in q.lines:
            qlines.append(
                {
                    "inquiry_line_id": ql.inquiry_line_id,
                    "unit_price": to_float(ql.unit_price),
                    "amount": to_float(ql.amount),
                }
            )
        quotes.append(
            {
                "id": q.id,
                "purchaser_id": q.purchaser_id,
                "purchaser_name": q.purchaser.name if q.purchaser else "",
                "note": q.note,
                "lead_days": q.lead_days,
                "total": to_float(q.total),
                "round_no": getattr(q, "round_no", 1) or 1,
                "created_at": fmt_dt(q.created_at),
                "selected": inq.selected_quote_id == q.id,
                "lines": qlines,
            }
        )
    return {
        "id": inq.id,
        "no": inq.no,
        "customer_name": inq.customer_name,
        "contact_name": inq.contact_name,
        "phone": inq.phone,
        "email": inq.email,
        "currency": inq.currency,
        "requirement": inq.requirement,
        "creator_id": inq.creator_id,
        "creator_name": inq.creator.name if inq.creator else "",
        "status": inq.status,
        "status_label": inquiry_status_label(inq),
        "close_reason": inq.close_reason,
        "quote_round": getattr(inq, "quote_round", 1) or 1,
        "requote_reason": inq.requote_reason or "",
        "requote_log": parse_requote_log(getattr(inq, "requote_log", "") or ""),
        "selected_quote_id": inq.selected_quote_id,
        "order_id": inq.order.id if inq.order else None,
        "order_no": inq.order.no if inq.order else None,
        "order_status": inq.order.status if inq.order else None,
        "can_open_order": bool(inq.order and can_view_order(user, inq.order)),
        "audit_rejected": bool((inq.audit_reject_order_no or "").strip() or (inq.audit_reject_remark or "").strip()),
        "audit_reject_remark": inq.audit_reject_remark or "",
        "audit_reject_order_no": inq.audit_reject_order_no or "",
        "created_at": fmt_dt(inq.created_at),
        "lines": lines,
        "quotes": quotes,
        "can_quote": user.role == "purchase" and inq.status in ("pending_quote", "quoted"),
        "can_select": user.role == "sales"
        and inq.creator_id == user.id
        and inq.status in ("quoted", "selling")
        and inq.order is None,
        "can_requote": user.role == "sales"
        and inq.creator_id == user.id
        and inq.status in ("quoted", "selling")
        and inq.order is None,
        "can_win": user.role == "sales"
        and inq.creator_id == user.id
        and inq.status == "selling"
        and bool(inq.selected_quote_id)
        and inq.order is None,
        "can_close": user.role == "sales"
        and inq.creator_id == user.id
        and inq.status in ("quoted", "selling")
        and inq.order is None,
        "can_win_or_close": user.role == "sales"
        and inq.creator_id == user.id
        and inq.status == "selling"
        and inq.order is None,
        "can_edit": user.role == "sales" and inq.creator_id == user.id and inq.status == "pending_quote" and not inq.quotes,
        "can_delete": user.role == "admin",
        "close_reason_options": list(CLOSE_REASONS),
    }


def load_inquiry(db: Session, inquiry_id: int):
    return (
        db.query(Inquiry)
        .options(
            joinedload(Inquiry.lines).joinedload(InquiryLine.product),
            joinedload(Inquiry.quotes).joinedload(Quote.lines),
            joinedload(Inquiry.quotes).joinedload(Quote.purchaser),
            joinedload(Inquiry.creator),
            joinedload(Inquiry.order),
        )
        .filter(Inquiry.id == inquiry_id)
        .first()
    )


def _ensure_order(db: Session, inq: Inquiry, user: User, comment: str) -> Order:
    if inq.order:
        return inq.order
    if not inq.selected_quote_id:
        raise HTTPException(400, "未选择报价，无法生成订单")
    order = Order(
        no=next_no(db, Order, "ORD"),
        inquiry_id=inq.id,
        quote_id=inq.selected_quote_id,
        status="pending_audit",
        creator_id=user.id,
        salesperson_id=inq.creator_id,
        customer_name=inq.customer_name,
        currency=inq.currency or "RMB",
        doc_date=date.today(),
    )
    db.add(order)
    db.flush()
    from app.api.orders import seed_order_lines

    seed_order_lines(db, order, inq, inq.selected_quote)
    db.add(
        OrderLog(
            order_id=order.id,
            from_status="",
            to_status="pending_audit",
            operator_id=user.id,
            comment=comment,
        )
    )
    return order


@router.get("")
def list_inquiries(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    status: str = "",
):
    if user.role not in ("admin", "sales", "purchase", "finance"):
        raise HTTPException(403, "没有权限")
    q = db.query(Inquiry).options(
        joinedload(Inquiry.creator),
        joinedload(Inquiry.order),
        joinedload(Inquiry.quotes),
    )
    q = filter_inquiries(q, user)
    if status in ("done", "won", "closed"):
        q = q.filter(Inquiry.status.in_(DONE_STATUSES))
    elif status:
        q = q.filter(Inquiry.status == status)
    rows = q.order_by(Inquiry.id.desc()).all()
    return [
        {
            "id": r.id,
            "no": r.no,
            "customer_name": r.customer_name,
            "currency": r.currency,
            "status": r.status,
            "status_label": inquiry_status_label(r),
            "creator_name": r.creator.name if r.creator else "",
            "quote_count": len(r.quotes) if r.quotes else 0,
            "order_no": r.order.no if r.order else None,
            "order_id": r.order.id if r.order else None,
            "created_at": fmt_dt(r.created_at),
        }
        for r in rows
    ]


@router.post("")
def create_inquiry(
    body: InquiryIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    if body.currency not in ("RMB", "USD", "EUR"):
        raise HTTPException(400, "币种仅支持 RMB / USD / EUR")
    if not body.lines:
        raise HTTPException(400, "至少一行产品")
    inq = Inquiry(
        no=next_no(db, Inquiry, "INQ"),
        customer_name=body.customer_name.strip(),
        contact_name=body.contact_name,
        phone=body.phone,
        email=body.email,
        currency=body.currency or "RMB",
        requirement=body.requirement,
        creator_id=user.id,
        status="pending_quote",
    )
    db.add(inq)
    db.flush()
    for ln in body.lines:
        db.add(make_inquiry_line(db, inq.id, ln))
    db.commit()
    return serialize_inquiry(load_inquiry(db, inq.id), user)


@router.get("/{inquiry_id}")
def get_inquiry(
    inquiry_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq or not can_view(user, inq):
        raise HTTPException(404, "询价单不存在")
    return serialize_inquiry(inq, user)


@router.patch("/{inquiry_id}")
def update_inquiry(
    inquiry_id: int,
    body: InquiryIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq or not can_view(user, inq):
        raise HTTPException(404, "询价单不存在")
    if inq.status != "pending_quote":
        raise HTTPException(400, "仅待报价状态可编辑")
    if inq.creator_id != user.id:
        raise HTTPException(403, "没有权限")
    inq.customer_name = body.customer_name.strip()
    inq.contact_name = body.contact_name
    inq.phone = body.phone
    inq.email = body.email
    inq.currency = body.currency or "RMB"
    inq.requirement = body.requirement
    db.query(InquiryLine).filter(InquiryLine.inquiry_id == inq.id).delete()
    for ln in body.lines:
        db.add(make_inquiry_line(db, inq.id, ln))
    db.commit()
    return serialize_inquiry(load_inquiry(db, inq.id), user)


@router.post("/{inquiry_id}/quotes")
def create_quote(
    inquiry_id: int,
    body: QuoteIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("purchase"))],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq:
        raise HTTPException(404, "询价单不存在")
    if inq.status not in ("pending_quote", "quoted"):
        if inq.status in ("selling", "won", "closed"):
            raise HTTPException(400, "该询价单已进入销售流程，采购不可再报价")
        raise HTTPException(400, "当前状态不可报价")
    line_ids = {ln.id for ln in inq.lines}
    if {x.inquiry_line_id for x in body.lines} != line_ids:
        raise HTTPException(400, "报价必须覆盖询价单全部明细")
    quote = Quote(
        inquiry_id=inq.id,
        purchaser_id=user.id,
        note=body.note,
        lead_days=body.lead_days or 0,
        round_no=getattr(inq, "quote_round", 1) or 1,
    )
    db.add(quote)
    db.flush()
    total = Decimal("0.00")
    qty_map = {ln.id: Decimal(str(ln.quantity)) for ln in inq.lines}
    for ln in body.lines:
        price = money(ln.unit_price)
        amount = (qty_map[ln.inquiry_line_id] * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += amount
        db.add(QuoteLine(quote_id=quote.id, inquiry_line_id=ln.inquiry_line_id, unit_price=price, amount=amount))
    quote.total = total
    inq.status = "quoted"
    db.commit()
    return serialize_inquiry(load_inquiry(db, inq.id), user)


@router.post("/{inquiry_id}/select-quote")
def select_quote(
    inquiry_id: int,
    body: SelectIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq or not can_view(user, inq):
        raise HTTPException(404, "询价单不存在")
    if inq.creator_id != user.id:
        raise HTTPException(403, "没有权限")
    if inq.status != "quoted" and not (inq.status == "selling" and not inq.order):
        raise HTTPException(400, "当前状态不可选择报价")
    quote = db.get(Quote, body.quote_id)
    if not quote or quote.inquiry_id != inq.id:
        raise HTTPException(400, "报价不存在")
    inq.selected_quote_id = quote.id
    inq.status = "selling"
    db.commit()
    return serialize_inquiry(load_inquiry(db, inq.id), user)


@router.post("/{inquiry_id}/close")
def close_inquiry(
    inquiry_id: int,
    body: CloseIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq or not can_view(user, inq):
        raise HTTPException(404, "询价单不存在")
    if inq.creator_id != user.id:
        raise HTTPException(403, "没有权限")
    if inq.order:
        raise HTTPException(400, "已生成订单，不能结束询价单")
    if inq.status not in ("quoted", "selling"):
        raise HTTPException(400, "当前状态不可结束")
    inq.close_reason = compose_close_reason(body)
    inq.status = "closed"
    db.commit()
    return serialize_inquiry(load_inquiry(db, inq.id), user)


@router.post("/{inquiry_id}/win")
def win_inquiry(
    inquiry_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq or not can_view(user, inq):
        raise HTTPException(404, "询价单不存在")
    if inq.creator_id != user.id:
        raise HTTPException(403, "没有权限")
    if inq.status != "selling" or not inq.selected_quote_id:
        raise HTTPException(400, "请先选择报价并处于销售中，再生成订单")
    if inq.order:
        if inq.status != "won":
            inq.status = "won"
            db.commit()
        loaded = load_inquiry(db, inq.id)
        return {"inquiry": serialize_inquiry(loaded, user), "order_id": inq.order.id, "order_no": inq.order.no}
    order = _ensure_order(db, inq, user, "提交管理员审核")
    inq.status = "won"
    inq.audit_reject_remark = ""
    inq.audit_reject_order_no = ""
    db.commit()
    loaded = load_inquiry(db, inq.id)
    return {"inquiry": serialize_inquiry(loaded, user), "order_id": order.id, "order_no": order.no}


@router.post("/{inquiry_id}/requote")
def requote_inquiry(
    inquiry_id: int,
    body: RequoteIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq or not can_view(user, inq):
        raise HTTPException(404, "询价单不存在")
    if inq.creator_id != user.id:
        raise HTTPException(403, "没有权限")
    if inq.order:
        raise HTTPException(400, "已生成订单，不能二次询价")
    if inq.status not in ("quoted", "selling"):
        raise HTTPException(400, "当前状态不可二次询价")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "请填写二次询价原因")
    next_round = (getattr(inq, "quote_round", 1) or 1) + 1
    inq.quote_round = next_round
    inq.requote_reason = reason
    log = parse_requote_log(getattr(inq, "requote_log", "") or "")
    log.append({"round": next_round, "reason": reason, "at": fmt_dt(utcnow())})
    inq.requote_log = json.dumps(log, ensure_ascii=False)
    inq.selected_quote_id = None
    inq.status = "pending_quote"
    db.commit()
    return serialize_inquiry(load_inquiry(db, inquiry_id), user)


@router.delete("/{inquiry_id}")
def delete_inquiry(
    inquiry_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    inq = load_inquiry(db, inquiry_id)
    if not inq:
        raise HTTPException(404, "询价单不存在")
    if inq.order:
        db.delete(inq.order)
        db.flush()
    inq.selected_quote_id = None
    db.flush()
    db.delete(inq)
    db.commit()
    return {"ok": True, "message": "询价单已删除"}
