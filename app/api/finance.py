from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.auth import get_current_user
from app.db.database import get_db
from app.db.models import (
    FinanceAllocLine,
    FinanceInvoice,
    FinancePayment,
    FinanceReceipt,
    FinanceSettleLine,
    FinanceVoucher,
    FinanceWriteoff,
    Inquiry,
    Order,
    PurchaseOrder,
    User,
)
from app.core.e2e import MoneyIn, money, names_equal, plain_name, to_api_money
from app.core.fx import CURRENCIES, norm_ccy, rates_payload, rmb_rates, to_rmb
from app.core.utils import fmt_dt, next_no, to_float

router = APIRouter(prefix="/api/finance", tags=["finance"])

FINANCE_ROLES = ("admin", "finance")
OPEN_ORDER_STATUSES = ("contract", "fulfilling", "done", "payment", "production", "shipping", "balance")
OPEN_PO_STATUSES = ("in_progress", "received", "inbound", "accepted", "done")
PROFIT_PO_SKIP = ("pending_fill", "pending_audit", "rejected")
PO_STATUS_LABEL = {
    "pending_fill": "待采购填写",
    "pending_audit": "待审核",
    "rejected": "已驳回",
    "in_progress": "进行中",
    "received": "收货",
    "inbound": "入库",
    "accepted": "验收",
    "done": "已完成",
}
SETTLE_METHODS = ("现金", "银行转账", "电汇", "支付宝", "微信", "支票")
RECEIPT_ACCOUNTS = ("现金", "基本户", "支付宝", "微信")
BIZ_TYPES_AR = ("应收账款", "预收账款", "其他应收")
BIZ_TYPES_AP = ("应付账款", "预付账款", "其他应付")


def require_finance(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in FINANCE_ROLES:
        raise HTTPException(403, "仅财务或管理员可登记收付和核销")
    return user


def require_finance_view(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in FINANCE_ROLES:
        raise HTTPException(403, "仅财务或管理员可查看资金管理")
    return user


def parse_iso_date(value: str) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def in_date_range(d: Optional[date], d0: Optional[date], d1: Optional[date]) -> bool:
    if d0 is None and d1 is None:
        return True
    if not d:
        return False
    if d0 and d < d0:
        return False
    if d1 and d > d1:
        return False
    return True


def order_doc_date(o: Optional[Order]) -> Optional[date]:
    if not o:
        return None
    if getattr(o, "doc_date", None):
        return o.doc_date
    if o.created_at:
        return o.created_at.date()
    return None


def po_doc_date(p: Optional[PurchaseOrder]) -> Optional[date]:
    if not p:
        return None
    if getattr(p, "doc_date", None):
        return p.doc_date
    if p.created_at:
        return p.created_at.date()
    return None


def voucher_matches_order(v: FinanceVoucher, order_id: int) -> bool:
    if not order_id:
        return True
    for a in v.allocs or []:
        if a.order_id == order_id:
            return True
        if a.purchase_order and a.purchase_order.sales_order_id == order_id:
            return True
    return False


def filter_voucher_rows(rows, date_from: str, date_to: str, order_id: int):
    d0, d1 = parse_iso_date(date_from), parse_iso_date(date_to)
    out = []
    for v in rows:
        if not in_date_range(v.biz_date, d0, d1):
            continue
        if not voucher_matches_order(v, order_id or 0):
            continue
        out.append(v)
    return out, d0, d1


def _month_keys(d0: date, d1: date) -> list:
    keys = []
    y, m = d0.year, d0.month
    while date(y, m, 1) <= d1:
        keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return keys


def _day_keys(d0: date, d1: date) -> list:
    keys = []
    d = d0
    while d <= d1:
        keys.append(d.isoformat())
        d += timedelta(days=1)
    return keys


def amount_chart(vouchers: list, d0: Optional[date], d1: Optional[date]) -> dict:
    dates = [v.biz_date for v in vouchers if v.biz_date]
    if not dates:
        return {"granularity": "day", "unit": "RMB", "points": []}
    start = d0 or min(dates)
    end = d1 or max(dates)
    if end < start:
        start, end = end, start
    monthly = (end - start).days > 62
    keys = _month_keys(start, end) if monthly else _day_keys(start, end)
    rec = {k: 0.0 for k in keys}
    pay = {k: 0.0 for k in keys}
    rates = rmb_rates()
    for v in vouchers:
        if not v.biz_date:
            continue
        key = v.biz_date.strftime("%Y-%m") if monthly else v.biz_date.isoformat()
        if key not in rec:
            continue
        settle = sum((money(s.amount) for s in v.settles), Decimal("0.00"))
        amt = float(to_rmb(settle, settle_currency(v), rates))
        if (v.voucher_type or "collect") == "refund":
            amt = -amt
        if v.direction == "receipt":
            rec[key] += amt
        else:
            pay[key] += amt
    return {
        "granularity": "month" if monthly else "day",
        "unit": "RMB",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "points": [{"date": k, "received": round(rec[k], 2), "paid": round(pay[k], 2)} for k in keys],
    }


class ReceiptIn(BaseModel):
    order_id: int
    amount: MoneyIn = 0
    biz_date: date
    method: str = "银行转账"
    remark: str = ""


class PaymentIn(BaseModel):
    purchase_order_id: int
    amount: MoneyIn = 0
    biz_date: date
    method: str = "银行转账"
    remark: str = ""


class InvoiceIn(BaseModel):
    kind: str
    order_id: Optional[int] = None
    purchase_order_id: Optional[int] = None
    invoice_no: str
    amount: MoneyIn = 0
    tax_amount: MoneyIn = 0
    biz_date: date
    remark: str = ""


class WriteoffIn(BaseModel):
    invoice_id: int
    receipt_id: Optional[int] = None
    payment_id: Optional[int] = None
    amount: MoneyIn = 0
    biz_date: date
    remark: str = ""


class SettleIn(BaseModel):
    method: str = "银行转账"
    account: str = ""
    amount: MoneyIn = 0
    currency: str = "RMB"
    remark: str = ""


class AllocIn(BaseModel):
    doc_type: str = "sales_order"
    order_id: Optional[int] = None
    purchase_order_id: Optional[int] = None
    this_amount: MoneyIn = 0
    discount_amount: MoneyIn = 0


class VoucherIn(BaseModel):
    direction: str
    voucher_type: str = "collect"
    biz_date: date
    partner_name: str
    biz_type: str = ""
    salesperson_id: Optional[int] = None
    summary: str = ""
    remark: str = ""
    cash_discount: MoneyIn = 0
    settles: List[SettleIn] = Field(default_factory=list)
    allocs: List[AllocIn] = Field(default_factory=list)


def sum_col(db: Session, model, fk_name: str, fk_val: int, col="amount") -> float:
    rows = db.query(getattr(model, col)).filter(getattr(model, fk_name) == fk_val).all()
    total = Decimal("0.00")
    for (val,) in rows:
        total += money(val)
    return float(total)


def invoice_written(db: Session, invoice_id: int) -> float:
    return sum_col(db, FinanceWriteoff, "invoice_id", invoice_id)


def receipt_written(db: Session, receipt_id: int) -> float:
    return sum_col(db, FinanceWriteoff, "receipt_id", receipt_id)


def payment_written(db: Session, payment_id: int) -> float:
    return sum_col(db, FinanceWriteoff, "payment_id", payment_id)


def alloc_cash_discount(
    db: Session,
    *,
    order_id: Optional[int] = None,
    purchase_order_id: Optional[int] = None,
    exclude_voucher_id: Optional[int] = None,
) -> tuple[Decimal, Decimal]:
    q = db.query(FinanceAllocLine, FinanceVoucher).join(FinanceVoucher, FinanceAllocLine.voucher_id == FinanceVoucher.id)
    if order_id is not None:
        q = q.filter(FinanceAllocLine.order_id == order_id, FinanceVoucher.direction == "receipt")
    else:
        q = q.filter(FinanceAllocLine.purchase_order_id == purchase_order_id, FinanceVoucher.direction == "payment")
    if exclude_voucher_id:
        q = q.filter(FinanceVoucher.id != exclude_voucher_id)
    cash = Decimal("0.00")
    disc = Decimal("0.00")
    for line, voucher in q.all():
        sign = Decimal("-1") if voucher.voucher_type == "refund" else Decimal("1")
        cash += sign * money(line.this_amount)
        if voucher.voucher_type != "refund":
            disc += money(line.discount_amount)
    return cash, disc


def order_received(db: Session, order_id: int, exclude_voucher_id: Optional[int] = None) -> float:
    legacy = money(sum_col(db, FinanceReceipt, "order_id", order_id))
    cash, _ = alloc_cash_discount(db, order_id=order_id, exclude_voucher_id=exclude_voucher_id)
    return float(legacy + cash)


def order_discount(db: Session, order_id: int, exclude_voucher_id: Optional[int] = None) -> float:
    _, disc = alloc_cash_discount(db, order_id=order_id, exclude_voucher_id=exclude_voucher_id)
    return float(disc)


def po_paid(db: Session, po_id: int, exclude_voucher_id: Optional[int] = None) -> float:
    legacy = money(sum_col(db, FinancePayment, "purchase_order_id", po_id))
    cash, _ = alloc_cash_discount(db, purchase_order_id=po_id, exclude_voucher_id=exclude_voucher_id)
    return float(legacy + cash)


def po_discount(db: Session, po_id: int, exclude_voucher_id: Optional[int] = None) -> float:
    _, disc = alloc_cash_discount(db, purchase_order_id=po_id, exclude_voucher_id=exclude_voucher_id)
    return float(disc)


def settle_currency(voucher: FinanceVoucher) -> str:
    for s in voucher.settles or []:
        return norm_ccy(getattr(s, "currency", None))
    return "RMB"


def doc_currency(order: Optional[Order] = None, po: Optional[PurchaseOrder] = None) -> str:
    if po:
        return norm_ccy(getattr(po, "currency", None))
    if not order:
        return "RMB"
    return norm_ccy(getattr(order, "currency", None) or (order.inquiry.currency if order.inquiry else "RMB"))


def alloc_cash_rmb(
    db: Session,
    *,
    order_id: Optional[int] = None,
    purchase_order_id: Optional[int] = None,
    exclude_voucher_id: Optional[int] = None,
    rates=None,
) -> Decimal:
    rates = rates or rmb_rates()
    q = (
        db.query(FinanceAllocLine, FinanceVoucher)
        .join(FinanceVoucher, FinanceAllocLine.voucher_id == FinanceVoucher.id)
        .options(joinedload(FinanceVoucher.settles))
    )
    if order_id is not None:
        q = q.filter(FinanceAllocLine.order_id == order_id, FinanceVoucher.direction == "receipt")
        legacy = money(sum_col(db, FinanceReceipt, "order_id", order_id))
    else:
        q = q.filter(FinanceAllocLine.purchase_order_id == purchase_order_id, FinanceVoucher.direction == "payment")
        legacy = money(sum_col(db, FinancePayment, "purchase_order_id", purchase_order_id))
    if exclude_voucher_id:
        q = q.filter(FinanceVoucher.id != exclude_voucher_id)
    total = to_rmb(legacy, "RMB", rates)
    for line, voucher in q.all():
        sign = Decimal("-1") if voucher.voucher_type == "refund" else Decimal("1")
        total += sign * to_rmb(money(line.this_amount), settle_currency(voucher), rates)
    return money(total)


def order_customer(order: Optional[Order]) -> str:
    if not order:
        return ""
    return (getattr(order, "customer_name", None) or "") or (order.inquiry.customer_name if order.inquiry else "")


def order_contract(o: Order) -> float:
    t = money(getattr(o, "total", 0))
    if t > 0:
        return float(t)
    if o.quote:
        return float(money(o.quote.total))
    return 0.0


def load_voucher(db: Session, voucher_id: int) -> Optional[FinanceVoucher]:
    return (
        db.query(FinanceVoucher)
        .options(
            joinedload(FinanceVoucher.settles),
            joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.order).joinedload(Order.inquiry).joinedload(Inquiry.creator),
            joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.purchase_order),
            joinedload(FinanceVoucher.salesperson),
            joinedload(FinanceVoucher.operator),
        )
        .filter(FinanceVoucher.id == voucher_id)
        .first()
    )


def serialize_voucher(v: FinanceVoucher) -> dict:
    settle_total = sum((money(s.amount) for s in v.settles), Decimal("0.00"))
    alloc_cash = sum((money(a.this_amount) for a in v.allocs), Decimal("0.00"))
    alloc_disc = sum((money(a.discount_amount) for a in v.allocs), Decimal("0.00"))
    cash_disc = money(v.cash_discount)
    return {
        "id": v.id,
        "no": v.no,
        "direction": v.direction,
        "voucher_type": v.voucher_type,
        "type_label": "退款" if v.voucher_type == "refund" else ("收款" if v.direction == "receipt" else "付款"),
        "biz_date": v.biz_date.isoformat(),
        "partner_name": v.partner_name,
        "biz_type": v.biz_type,
        "salesperson_id": v.salesperson_id,
        "salesperson_name": v.salesperson.name if v.salesperson else "",
        "summary": v.summary,
        "remark": v.remark,
        "status": v.status or "posted",
        "needs_fill": (v.status or "") == "pending",
        "cash_discount": to_api_money(cash_disc),
        "settle_total": to_api_money(settle_total),
        "currency": settle_currency(v),
        "final_amount": to_api_money(settle_total + cash_disc),
        "alloc_cash": to_api_money(alloc_cash),
        "alloc_discount": to_api_money(alloc_disc),
        "operator": v.operator.name if v.operator else "",
        "created_at": fmt_dt(v.created_at),
        "settles": [
            {
                "id": s.id,
                "method": s.method,
                "account": s.account,
                "amount": to_float(s.amount),
                "currency": norm_ccy(getattr(s, "currency", None)),
                "remark": s.remark,
            }
            for s in sorted(v.settles, key=lambda x: x.sort_no)
        ],
        "linked_po_nos": [
            a.purchase_order.no for a in v.allocs if a.purchase_order
        ],
        "linked_so_nos": [a.order.no for a in v.allocs if a.order],
        "allocs": [
            {
                "id": a.id,
                "doc_type": a.doc_type,
                "doc_type_label": "销售订单" if a.doc_type == "sales_order" else "采购订单",
                "order_id": a.order_id,
                "purchase_order_id": a.purchase_order_id,
                "doc_no": a.order.no if a.order else (a.purchase_order.no if a.purchase_order else ""),
                "partner_name": (
                    order_customer(a.order)
                    if a.order
                    else (a.purchase_order.supplier_name if a.purchase_order else v.partner_name)
                ),
                "salesperson_name": a.order.inquiry.creator.name if a.order and a.order.inquiry and a.order.inquiry.creator else "",
                "this_amount": to_float(a.this_amount),
                "discount_amount": to_float(a.discount_amount),
            }
            for a in v.allocs
        ],
    }


@router.get("/meta")
def finance_meta(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_finance_view)]):
    salespeople = db.query(User).filter(User.role == "sales", User.is_active.is_(True)).order_by(User.id).all()
    return {
        "settle_methods": list(SETTLE_METHODS),
        "accounts": list(RECEIPT_ACCOUNTS),
        "biz_types_ar": list(BIZ_TYPES_AR),
        "biz_types_ap": list(BIZ_TYPES_AP),
        "salespeople": [{"id": u.id, "name": u.name} for u in salespeople],
        "today": date.today().isoformat(),
        "currencies": list(CURRENCIES),
        "fx": rates_payload(),
    }


@router.get("/partners")
def list_partners(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_finance_view)],
    direction: str = "receipt",
):
    if direction == "payment":
        rows = (
            db.query(PurchaseOrder.supplier_name)
            .filter(PurchaseOrder.status.in_(OPEN_PO_STATUSES), PurchaseOrder.supplier_name != "")
            .distinct()
            .order_by(PurchaseOrder.supplier_name)
            .all()
        )
        return [{"name": r[0]} for r in rows if r[0]]
    if direction == "receipt":
        names = set()
        inq_rows = (
            db.query(Inquiry.customer_name)
            .join(Order, Order.inquiry_id == Inquiry.id)
            .filter(Order.status.in_(OPEN_ORDER_STATUSES))
            .distinct()
            .all()
        )
        own_rows = (
            db.query(Order.customer_name)
            .filter(Order.status.in_(OPEN_ORDER_STATUSES), Order.customer_name != "")
            .distinct()
            .all()
        )
        names.update(r[0] for r in inq_rows if r[0])
        names.update(r[0] for r in own_rows if r[0])
        return [{"name": n} for n in sorted(names)]


@router.get("/open-docs")
def list_open_docs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_finance_view)],
    direction: str = "receipt",
    voucher_type: str = "collect",
    partner: str = "",
    q: str = "",
    exclude_voucher_id: int = 0,
):
    partner = (partner or "").strip()
    keyword = (q or "").strip()
    is_refund = voucher_type == "refund"
    if direction == "payment":
        rows = (
            db.query(PurchaseOrder)
            .filter(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
            .order_by(PurchaseOrder.id.desc())
            .all()
        )
        out = []
        unpaid = Decimal("0.00")
        for p in rows:
            if partner and not names_equal(p.supplier_name, partner):
                continue
            if keyword and keyword.lower() not in f"{p.no} {plain_name(p.supplier_name)}".lower():
                continue
            total = money(p.total)
            paid = money(po_paid(db, p.id, exclude_voucher_id=exclude_voucher_id or None))
            disc = money(po_discount(db, p.id, exclude_voucher_id=exclude_voucher_id or None))
            pending = paid if is_refund else total - paid - disc
            if pending <= 0:
                continue
            unpaid += pending
            out.append(
                {
                    "doc_type": "purchase_order",
                    "doc_type_label": "采购订单",
                    "purchase_order_id": p.id,
                    "order_id": None,
                    "doc_no": p.no,
                    "doc_date": p.created_at.date().isoformat() if p.created_at else None,
                    "due_date": p.expected_date.isoformat() if p.expected_date else None,
                    "total": to_api_money(total),
                    "pending": to_api_money(pending),
                    "partner_name": p.supplier_name,
                    "salesperson_name": "",
                    "department_name": "采购部",
                }
            )
        return {"items": out, "unpaid_total": to_api_money(unpaid)}
    rows = (
        db.query(Order)
        .options(joinedload(Order.inquiry).joinedload(Inquiry.creator), joinedload(Order.quote))
        .filter(Order.status.in_(OPEN_ORDER_STATUSES))
        .order_by(Order.id.desc())
        .all()
    )
    out = []
    unpaid = Decimal("0.00")
    for o in rows:
        customer = order_customer(o)
        if partner and not names_equal(customer, partner):
            continue
        if keyword and keyword.lower() not in f"{o.no} {plain_name(customer)} {o.contract_no or ''}".lower():
            continue
        total = money(order_contract(o))
        received = money(order_received(db, o.id, exclude_voucher_id=exclude_voucher_id or None))
        disc = money(order_discount(db, o.id, exclude_voucher_id=exclude_voucher_id or None))
        pending = received if is_refund else total - received - disc
        if pending <= 0:
            continue
        unpaid += pending
        due = o.contract_date.isoformat() if o.contract_date else (o.created_at.date().isoformat() if o.created_at else None)
        out.append(
            {
                "doc_type": "sales_order",
                "doc_type_label": "销售订单",
                "order_id": o.id,
                "purchase_order_id": None,
                "doc_no": o.no,
                "doc_date": o.created_at.date().isoformat() if o.created_at else None,
                "due_date": due,
                "total": to_api_money(total),
                "pending": to_api_money(pending),
                "partner_name": customer,
                "salesperson_name": o.inquiry.creator.name if o.inquiry and o.inquiry.creator else "",
                "department_name": "销售部",
            }
        )
    return {"items": out, "unpaid_total": to_api_money(unpaid)}


@router.get("/vouchers")
def list_vouchers(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_finance_view)],
    direction: str = "",
    date_from: str = "",
    date_to: str = "",
    order_id: int = 0,
):
    q = db.query(FinanceVoucher).options(
        joinedload(FinanceVoucher.operator),
        joinedload(FinanceVoucher.settles),
        joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.purchase_order),
        joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.order),
    )
    if direction in ("receipt", "payment"):
        q = q.filter(FinanceVoucher.direction == direction)
    rows, _, _ = filter_voucher_rows(q.order_by(FinanceVoucher.id.desc()).all(), date_from, date_to, order_id)
    out = []
    for v in rows:
        settle_total = sum((money(s.amount) for s in v.settles), Decimal("0.00"))
        po_nos = "、".join(dict.fromkeys(a.purchase_order.no for a in v.allocs if a.purchase_order))
        so_nos = "、".join(dict.fromkeys(a.order.no for a in v.allocs if a.order))
        out.append(
            {
                "id": v.id,
                "no": v.no,
                "direction": v.direction,
                "voucher_type": v.voucher_type,
                "type_label": "退款" if v.voucher_type == "refund" else ("收款" if v.direction == "receipt" else "付款"),
                "biz_date": v.biz_date.isoformat(),
                "partner_name": v.partner_name,
                "linked_docs": po_nos if v.direction == "payment" else so_nos,
                "settle_total": to_api_money(settle_total),
                "currency": settle_currency(v),
                "cash_discount": to_api_money(v.cash_discount),
                "final_amount": to_api_money(settle_total + money(v.cash_discount)),
                "summary": v.summary,
                "remark": v.remark or "",
                "status": v.status or "posted",
                "needs_fill": (v.status or "") == "pending",
                "operator": v.operator.name if v.operator else "",
            }
        )
    return out


@router.get("/vouchers/{voucher_id}")
def get_voucher(
    voucher_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_finance_view)],
):
    v = load_voucher(db, voucher_id)
    if not v:
        raise HTTPException(404, "单据不存在")
    return serialize_voucher(v)


def apply_voucher_lines(db: Session, voucher: FinanceVoucher, body: VoucherIn) -> None:
    partner = (body.partner_name or "").strip()
    if body.voucher_type not in ("collect", "refund"):
        raise HTTPException(400, "类型仅为收款/付款或退款")
    cash_disc = money(body.cash_discount)
    if cash_disc < 0:
        raise HTTPException(400, "现金折扣不能为负")
    if body.voucher_type == "refund" and cash_disc > 0:
        raise HTTPException(400, "退款单不使用现金折扣")
    linked = []
    for a in body.allocs:
        if body.direction == "payment" and a.purchase_order_id:
            linked.append(a)
        elif body.direction == "receipt" and a.order_id:
            linked.append(a)
    if body.direction == "payment" and not linked:
        raise HTTPException(400, "付款单必须关联采购单")
    if body.direction == "receipt" and not linked:
        raise HTTPException(400, "收款单必须关联销售订单，客户打款后请选择对应销售单登记")
    if not partner and body.direction == "payment":
        po0 = db.get(PurchaseOrder, linked[0].purchase_order_id)
        partner = (po0.supplier_name if po0 else "") or ""
    if not partner and body.direction == "receipt":
        order0 = db.get(Order, linked[0].order_id)
        partner = order_customer(order0)
    if not partner:
        raise HTTPException(400, "请填写往来单位")
    settle_rows = list(body.settles) or [SettleIn()]
    currencies = {norm_ccy(s.currency) for s in settle_rows}
    if not currencies.issubset(set(CURRENCIES)):
        raise HTTPException(400, "币种仅为 RMB / USD / EUR")
    if len(currencies) > 1:
        raise HTTPException(400, "同一收付款单结算行币种须一致")
    settle_total = sum((money(s.amount) for s in settle_rows), Decimal("0.00"))
    money_allocs = [a for a in linked if money(a.this_amount) > 0 or money(a.discount_amount) > 0]
    alloc_cash = sum((money(a.this_amount) for a in money_allocs), Decimal("0.00"))
    alloc_disc = sum((money(a.discount_amount) for a in money_allocs), Decimal("0.00"))
    if settle_total > 0 or alloc_cash > 0 or cash_disc > 0:
        if alloc_cash != settle_total:
            raise HTTPException(400, f"本次收/付款金额合计须等于结算合计 {settle_total}")
        if alloc_disc != cash_disc:
            raise HTTPException(400, f"单据折扣合计须等于现金折扣 {cash_disc}")
        if settle_total <= 0:
            raise HTTPException(400, "请至少填写一行结算金额")
    salesperson = db.get(User, body.salesperson_id) if body.salesperson_id else None
    if body.salesperson_id and (not salesperson or salesperson.role != "sales"):
        raise HTTPException(400, "业务员不存在")
    default_biz = "应收账款" if voucher.direction == "receipt" else "应付账款"
    voucher.voucher_type = body.voucher_type
    voucher.biz_date = body.biz_date
    voucher.partner_name = partner
    voucher.biz_type = (body.biz_type or "").strip() or default_biz
    voucher.salesperson_id = salesperson.id if salesperson else None
    voucher.summary = (body.summary or "").strip()
    voucher.remark = (body.remark or "").strip()
    voucher.status = "posted"
    voucher.cash_discount = cash_disc
    db.query(FinanceSettleLine).filter(FinanceSettleLine.voucher_id == voucher.id).delete()
    db.query(FinanceAllocLine).filter(FinanceAllocLine.voucher_id == voucher.id).delete()
    db.flush()
    for i, s in enumerate(settle_rows, start=1):
        db.add(
            FinanceSettleLine(
                voucher_id=voucher.id,
                sort_no=i,
                method=(s.method or "银行转账").strip() or "银行转账",
                account=(s.account or "").strip(),
                amount=money(s.amount),
                currency=norm_ccy(s.currency),
                remark=(s.remark or "").strip(),
            )
        )
    exclude = voucher.id
    for a in linked:
        this_amt = money(a.this_amount)
        disc_amt = money(a.discount_amount)
        if this_amt < 0 or disc_amt < 0:
            raise HTTPException(400, "核销金额不能为负")
        if voucher.direction == "receipt":
            order = db.get(Order, a.order_id)
            if not order or order.status in ("pending_audit", "rejected", "draft"):
                raise HTTPException(400, "只能登记已审核销售订单")
            received = money(order_received(db, order.id, exclude))
            if voucher.voucher_type == "refund":
                if disc_amt > 0:
                    raise HTTPException(400, "退款不使用折扣")
                if this_amt > received:
                    raise HTTPException(400, f"{order.no} 退款不能超过已收款 {received}")
            db.add(
                FinanceAllocLine(
                    voucher_id=voucher.id,
                    doc_type="sales_order",
                    order_id=order.id,
                    this_amount=this_amt,
                    discount_amount=disc_amt,
                )
            )
        else:
            po = db.get(PurchaseOrder, a.purchase_order_id)
            if not po or po.status in ("pending_fill", "pending_audit", "rejected"):
                raise HTTPException(400, "只能关联已生效采购单")
            po_total = money(po.total)
            pending = po_total - money(po_paid(db, po.id, exclude)) - money(po_discount(db, po.id, exclude))
            paid = money(po_paid(db, po.id, exclude))
            if voucher.voucher_type == "refund":
                if disc_amt > 0:
                    raise HTTPException(400, "退款不使用折扣")
                if this_amt > paid:
                    raise HTTPException(400, f"{po.no} 退款不能超过已付款 {paid}")
            elif po_total > 0 and this_amt + disc_amt > pending:
                raise HTTPException(400, f"{po.no} 付款不能超过待付 {pending}")
            db.add(
                FinanceAllocLine(
                    voucher_id=voucher.id,
                    doc_type="purchase_order",
                    purchase_order_id=po.id,
                    this_amount=this_amt,
                    discount_amount=disc_amt,
                )
            )


def po_first_payment_amount(po: PurchaseOrder) -> Decimal:
    goods = sum((money(ln.amount) for ln in (po.lines or [])), Decimal("0.00"))
    order_amount = goods + money(getattr(po, "freight", 0)) + money(getattr(po, "extra_tax", 0))
    deposit = money(getattr(po, "deposit", 0))
    if getattr(po, "pay_deposit", False) and deposit > 0:
        return deposit
    if order_amount > 0:
        return order_amount
    return money(getattr(po, "total", 0))


def ensure_payment_voucher_for_po(db: Session, po: PurchaseOrder, user: User) -> None:
    amt = po_first_payment_amount(po)
    alloc = db.query(FinanceAllocLine).filter(FinanceAllocLine.purchase_order_id == po.id).first()
    if alloc:
        voucher = db.get(FinanceVoucher, alloc.voucher_id)
        if voucher and (voucher.status or "") != "posted":
            voucher.status = "pending"
        if amt > 0 and money(alloc.this_amount) == 0:
            alloc.this_amount = amt
            voucher = db.get(FinanceVoucher, alloc.voucher_id)
            if voucher:
                filled = False
                for s in voucher.settles:
                    if money(s.amount) == 0:
                        s.amount = amt
                        filled = True
                        break
                if not filled and not voucher.settles:
                    db.add(
                        FinanceSettleLine(
                            voucher_id=voucher.id,
                            sort_no=1,
                            method=(getattr(po, "settle_method", None) or "银行转账").strip() or "银行转账",
                            account=(getattr(po, "pay_account", None) or "").strip(),
                            amount=amt,
                            currency=norm_ccy(getattr(po, "currency", None)),
                            remark="",
                        )
                    )
        return
    voucher = FinanceVoucher(
        no=next_no(db, FinanceVoucher, "FK"),
        direction="payment",
        voucher_type="collect",
        biz_date=date.today(),
        partner_name=(po.supplier_name or "").strip() or "待填写",
        biz_type="应付账款",
        salesperson_id=getattr(po, "purchaser_id", None),
        summary=f"采购单 {po.no} 待登记付款",
        remark="",
        status="pending",
        cash_discount=0,
        operator_id=user.id,
    )
    db.add(voucher)
    db.flush()
    db.add(
        FinanceSettleLine(
            voucher_id=voucher.id,
            sort_no=1,
            method=(getattr(po, "settle_method", None) or "银行转账").strip() or "银行转账",
            account=(getattr(po, "pay_account", None) or "").strip(),
            amount=amt,
            currency=norm_ccy(getattr(po, "currency", None)),
            remark="",
        )
    )
    db.add(
        FinanceAllocLine(
            voucher_id=voucher.id,
            doc_type="purchase_order",
            purchase_order_id=po.id,
            this_amount=amt,
            discount_amount=0,
        )
    )


@router.post("/vouchers")
def create_voucher(
    body: VoucherIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_finance)],
):
    if body.direction not in ("receipt", "payment"):
        raise HTTPException(400, "direction 仅为 receipt 或 payment")
    prefix = "SK" if body.direction == "receipt" else "FK"
    voucher = FinanceVoucher(
        no=next_no(db, FinanceVoucher, prefix),
        direction=body.direction,
        voucher_type=body.voucher_type,
        biz_date=body.biz_date,
        partner_name=(body.partner_name or "").strip(),
        operator_id=user.id,
        cash_discount=0,
    )
    db.add(voucher)
    db.flush()
    apply_voucher_lines(db, voucher, body)
    db.commit()
    return serialize_voucher(load_voucher(db, voucher.id))


@router.put("/vouchers/{voucher_id}")
def update_voucher(
    voucher_id: int,
    body: VoucherIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_finance)],
):
    voucher = load_voucher(db, voucher_id)
    if not voucher:
        raise HTTPException(404, "单据不存在")
    if body.direction and body.direction != voucher.direction:
        raise HTTPException(400, "不能更改收付款方向")
    apply_voucher_lines(db, voucher, body)
    voucher.operator_id = user.id
    db.commit()
    return serialize_voucher(load_voucher(db, voucher.id))


@router.get("/linkable-docs")
def linkable_docs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_finance_view)],
    direction: str = "payment",
):
    if direction == "payment":
        rows = (
            db.query(PurchaseOrder)
            .options(joinedload(PurchaseOrder.sales_order))
            .filter(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
            .order_by(PurchaseOrder.id.desc())
            .all()
        )
        return [
            {
                "id": p.id,
                "no": p.no,
                "partner_name": p.supplier_name,
                "total": to_float(p.total),
                "currency": doc_currency(po=p),
                "sales_order_id": p.sales_order_id,
                "sales_order_no": p.sales_order.no if p.sales_order else "",
            }
            for p in rows
        ]
    rows = (
        db.query(Order)
        .options(joinedload(Order.inquiry), joinedload(Order.quote))
        .filter(Order.status.in_(OPEN_ORDER_STATUSES))
        .order_by(Order.id.desc())
        .all()
    )
    return [
        {
            "id": o.id,
            "no": o.no,
            "partner_name": order_customer(o),
            "total": to_api_money(order_contract(o)),
            "currency": doc_currency(order=o),
        }
        for o in rows
    ]


@router.get("/profit")
def profit_by_purchase(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_finance_view)],
    date_from: str = "",
    date_to: str = "",
    order_id: int = 0,
):
    pos = (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.sales_order).joinedload(Order.inquiry),
            joinedload(PurchaseOrder.sales_order).joinedload(Order.quote),
        )
        .filter(PurchaseOrder.status.notin_(PROFIT_PO_SKIP))
        .order_by(PurchaseOrder.id.desc())
        .all()
    )
    d0, d1 = parse_iso_date(date_from), parse_iso_date(date_to)
    if order_id:
        pos = [p for p in pos if p.sales_order_id == order_id]
    if d0 or d1:
        pos = [
            p
            for p in pos
            if in_date_range(po_doc_date(p) or order_doc_date(p.sales_order), d0, d1)
        ]
    items = []
    fx = rates_payload()
    rates = rmb_rates()
    for p in pos:
        paid = float(alloc_cash_rmb(db, purchase_order_id=p.id, rates=rates))
        so = p.sales_order
        received = float(alloc_cash_rmb(db, order_id=so.id, rates=rates)) if so else 0.0
        so_amt = float(to_rmb(order_contract(so), doc_currency(order=so), rates)) if so else 0.0
        po_amt = float(to_rmb(money(p.total), doc_currency(po=p), rates))
        items.append(
            {
                "purchase_order_id": p.id,
                "po_no": p.no,
                "status": p.status,
                "status_label": PO_STATUS_LABEL.get(p.status, p.status),
                "supplier_name": p.supplier_name,
                "po_currency": doc_currency(po=p),
                "po_amount": to_api_money(po_amt),
                "paid": to_api_money(paid),
                "sales_order_id": p.sales_order_id,
                "so_no": so.no if so else "",
                "customer_name": order_customer(so),
                "so_currency": doc_currency(order=so) if so else "",
                "so_amount": to_api_money(so_amt),
                "received": to_api_money(received),
                "profit": to_api_money(round(received - paid, 2)),
            }
        )
    return {"items": items, "fx": fx, "unit": "RMB"}


@router.get("/summary")
def summary(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_finance_view)],
    date_from: str = "",
    date_to: str = "",
    order_id: int = 0,
):
    orders = (
        db.query(Order)
        .options(joinedload(Order.inquiry), joinedload(Order.quote))
        .filter(Order.status.in_(OPEN_ORDER_STATUSES))
        .order_by(Order.id.desc())
        .all()
    )
    pos = (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.sales_order))
        .filter(PurchaseOrder.status.notin_(PROFIT_PO_SKIP))
        .order_by(PurchaseOrder.id.desc())
        .all()
    )
    d0, d1 = parse_iso_date(date_from), parse_iso_date(date_to)
    if order_id:
        orders = [o for o in orders if o.id == order_id]
        pos = [p for p in pos if p.sales_order_id == order_id]
    if d0 or d1:
        orders = [o for o in orders if in_date_range(order_doc_date(o), d0, d1)]
        pos = [p for p in pos if in_date_range(po_doc_date(p) or order_doc_date(p.sales_order), d0, d1)]
    vouchers = (
        db.query(FinanceVoucher)
        .options(
            joinedload(FinanceVoucher.settles),
            joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.purchase_order),
            joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.order),
        )
        .all()
    )
    vouchers, _, _ = filter_voucher_rows(vouchers, date_from, date_to, order_id)
    chart = amount_chart(vouchers, d0, d1)
    sales_rows = []
    ar_total = rec_total = 0.0
    fx = rates_payload()
    rates = rmb_rates()
    for o in orders:
        ccy = doc_currency(order=o)
        contract_amt = float(to_rmb(order_contract(o), ccy, rates))
        received = float(alloc_cash_rmb(db, order_id=o.id, rates=rates))
        disc = float(to_rmb(order_discount(db, o.id), ccy, rates))
        invoiced = float(
            to_rmb(
                sum((money(inv.total) for inv in db.query(FinanceInvoice).filter(FinanceInvoice.order_id == o.id).all()), Decimal("0.00")),
                ccy,
                rates,
            )
        )
        written = received + disc
        ar_total += contract_amt or 0
        rec_total += received
        sales_rows.append(
            {
                "order_id": o.id,
                "no": o.no,
                "customer_name": (getattr(o, "customer_name", None) or "") or (o.inquiry.customer_name if o.inquiry else ""),
                "currency": ccy,
                "contract_amount": to_api_money(contract_amt),
                "received": to_api_money(received),
                "invoiced": to_api_money(invoiced),
                "written_off": to_api_money(written),
                "open_ar": to_api_money((contract_amt or 0) - received - disc),
            }
        )
    ap_total = pay_total = 0.0
    po_rows = []
    for p in pos:
        ccy = doc_currency(po=p)
        paid = float(alloc_cash_rmb(db, purchase_order_id=p.id, rates=rates))
        disc = float(to_rmb(po_discount(db, p.id), ccy, rates))
        invoiced = float(
            to_rmb(
                sum(
                    (money(inv.total) for inv in db.query(FinanceInvoice).filter(FinanceInvoice.purchase_order_id == p.id).all()),
                    Decimal("0.00"),
                ),
                ccy,
                rates,
            )
        )
        amt = float(to_rmb(money(p.total), ccy, rates))
        ap_total += amt
        pay_total += paid
        po_rows.append(
            {
                "purchase_order_id": p.id,
                "no": p.no,
                "status": p.status,
                "status_label": PO_STATUS_LABEL.get(p.status, p.status),
                "supplier_name": p.supplier_name,
                "currency": ccy,
                "contract_amount": to_api_money(amt),
                "paid": to_api_money(paid),
                "invoiced": to_api_money(invoiced),
                "written_off": to_api_money(paid + disc),
                "open_ap": to_api_money(amt - paid - disc),
            }
        )
    return {
        "fx": fx,
        "unit": "RMB",
        "cards": [
            {"key": "ar", "label": "销售合同额", "count": to_api_money(ar_total)},
            {"key": "received", "label": "累计收款", "count": to_api_money(rec_total)},
            {"key": "ap", "label": "采购合同额", "count": to_api_money(ap_total)},
            {"key": "paid", "label": "累计付款", "count": to_api_money(pay_total)},
        ],
        "sales": sales_rows,
        "purchases": po_rows,
        "chart": chart,
    }


@router.get("/receipts")
def list_receipts(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_finance)]):
    rows = db.query(FinanceReceipt).options(joinedload(FinanceReceipt.order).joinedload(Order.inquiry), joinedload(FinanceReceipt.operator)).order_by(FinanceReceipt.id.desc()).all()
    return [
        {
            "id": r.id,
            "order_id": r.order_id,
            "order_no": r.order.no if r.order else "",
            "customer_name": r.order.inquiry.customer_name if r.order and r.order.inquiry else "",
            "amount": to_float(r.amount),
            "written": to_api_money(receipt_written(db, r.id)),
            "open": to_api_money(money(r.amount) - money(receipt_written(db, r.id))),
            "biz_date": r.biz_date.isoformat(),
            "method": r.method,
            "remark": r.remark,
            "operator": r.operator.name if r.operator else "",
            "created_at": fmt_dt(r.created_at),
        }
        for r in rows
    ]


@router.post("/receipts")
def create_receipt(
    body: ReceiptIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_finance)],
):
    order = db.get(Order, body.order_id)
    if not order or order.status in ("pending_audit", "rejected"):
        raise HTTPException(400, "只能对已审核销售订单登记收款")
    row = FinanceReceipt(
        order_id=order.id,
        amount=money(body.amount),
        biz_date=body.biz_date,
        method=body.method.strip() or "银行转账",
        remark=body.remark,
        operator_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "ok": True}


@router.get("/payments")
def list_payments(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_finance)]):
    rows = (
        db.query(FinancePayment)
        .options(joinedload(FinancePayment.purchase_order), joinedload(FinancePayment.operator))
        .order_by(FinancePayment.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "purchase_order_id": r.purchase_order_id,
            "po_no": r.purchase_order.no if r.purchase_order else "",
            "supplier_name": r.purchase_order.supplier_name if r.purchase_order else "",
            "amount": to_float(r.amount),
            "written": to_api_money(payment_written(db, r.id)),
            "open": to_api_money(money(r.amount) - money(payment_written(db, r.id))),
            "biz_date": r.biz_date.isoformat(),
            "method": r.method,
            "remark": r.remark,
            "operator": r.operator.name if r.operator else "",
            "created_at": fmt_dt(r.created_at),
        }
        for r in rows
    ]


@router.post("/payments")
def create_payment(
    body: PaymentIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_finance)],
):
    po = db.get(PurchaseOrder, body.purchase_order_id)
    if not po or po.status in ("pending_fill", "pending_audit", "rejected"):
        raise HTTPException(400, "只能对已审核生效的采购单登记付款")
    row = FinancePayment(
        purchase_order_id=po.id,
        amount=money(body.amount),
        biz_date=body.biz_date,
        method=body.method.strip() or "银行转账",
        remark=body.remark,
        operator_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "ok": True}


@router.get("/invoices")
def list_invoices(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_finance)]):
    rows = (
        db.query(FinanceInvoice)
        .options(joinedload(FinanceInvoice.order), joinedload(FinanceInvoice.purchase_order), joinedload(FinanceInvoice.operator))
        .order_by(FinanceInvoice.id.desc())
        .all()
    )
    out = []
    for r in rows:
        w = invoice_written(db, r.id)
        total = money(r.total)
        out.append(
            {
                "id": r.id,
                "kind": r.kind,
                "kind_label": "销售开票" if r.kind == "sales" else "采购收票",
                "invoice_no": r.invoice_no,
                "order_id": r.order_id,
                "order_no": r.order.no if r.order else "",
                "purchase_order_id": r.purchase_order_id,
                "po_no": r.purchase_order.no if r.purchase_order else "",
                "amount": to_float(r.amount),
                "tax_amount": to_float(r.tax_amount),
                "total": to_api_money(total),
                "written": to_api_money(w),
                "open": to_api_money(total - money(w)),
                "biz_date": r.biz_date.isoformat(),
                "remark": r.remark,
                "operator": r.operator.name if r.operator else "",
            }
        )
    return out


@router.post("/invoices")
def create_invoice(
    body: InvoiceIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_finance)],
):
    kind = body.kind.strip()
    if kind not in ("sales", "purchase"):
        raise HTTPException(400, "开票类型为 sales 或 purchase")
    if not body.invoice_no.strip():
        raise HTTPException(400, "发票号必填")
    if kind == "sales":
        if not body.order_id:
            raise HTTPException(400, "销售开票需选择销售订单")
        order = db.get(Order, body.order_id)
        if not order or order.status in ("pending_audit", "rejected"):
            raise HTTPException(400, "销售订单未审核通过")
    else:
        if not body.purchase_order_id:
            raise HTTPException(400, "采购收票需选择采购单")
        po = db.get(PurchaseOrder, body.purchase_order_id)
        if not po or po.status in ("pending_fill", "pending_audit", "rejected"):
            raise HTTPException(400, "采购单未审核生效")
    amt = money(body.amount)
    tax = money(body.tax_amount)
    row = FinanceInvoice(
        kind=kind,
        order_id=body.order_id if kind == "sales" else None,
        purchase_order_id=body.purchase_order_id if kind == "purchase" else None,
        invoice_no=body.invoice_no.strip(),
        amount=amt,
        tax_amount=tax,
        total=amt + tax,
        biz_date=body.biz_date,
        remark=body.remark,
        operator_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "ok": True}


@router.post("/writeoffs")
def create_writeoff(
    body: WriteoffIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_finance)],
):
    inv = db.get(FinanceInvoice, body.invoice_id)
    if not inv:
        raise HTTPException(404, "发票不存在")
    amt = money(body.amount)
    open_inv = money(inv.total) - money(invoice_written(db, inv.id))
    if amt > open_inv:
        raise HTTPException(400, "核销金额超过发票未核销余额")
    if inv.kind == "sales":
        if not body.receipt_id:
            raise HTTPException(400, "销售发票请选择一笔收款核销")
        rec = db.get(FinanceReceipt, body.receipt_id)
        if not rec or rec.order_id != inv.order_id:
            raise HTTPException(400, "收款与发票必须属于同一销售订单")
        open_r = money(rec.amount) - money(receipt_written(db, rec.id))
        if amt > open_r:
            raise HTTPException(400, "核销金额超过该笔收款未核销余额")
        pay_id = None
        rec_id = rec.id
    else:
        if not body.payment_id:
            raise HTTPException(400, "采购发票请选择一笔付款核销")
        pay = db.get(FinancePayment, body.payment_id)
        if not pay or pay.purchase_order_id != inv.purchase_order_id:
            raise HTTPException(400, "付款与发票必须属于同一采购单")
        open_p = money(pay.amount) - money(payment_written(db, pay.id))
        if amt > open_p:
            raise HTTPException(400, "核销金额超过该笔付款未核销余额")
        rec_id = None
        pay_id = pay.id
    row = FinanceWriteoff(
        invoice_id=inv.id,
        receipt_id=rec_id,
        payment_id=pay_id,
        amount=amt,
        biz_date=body.biz_date,
        remark=body.remark,
        operator_id=user.id,
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "ok": True}


@router.get("/writeoffs")
def list_writeoffs(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_finance)]):
    rows = (
        db.query(FinanceWriteoff)
        .options(joinedload(FinanceWriteoff.invoice), joinedload(FinanceWriteoff.operator))
        .order_by(FinanceWriteoff.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "invoice_no": r.invoice.invoice_no if r.invoice else "",
            "kind": r.invoice.kind if r.invoice else "",
            "amount": to_float(r.amount),
            "receipt_id": r.receipt_id,
            "payment_id": r.payment_id,
            "biz_date": r.biz_date.isoformat(),
            "remark": r.remark,
            "operator": r.operator.name if r.operator else "",
        }
        for r in rows
    ]


@router.get("/options")
def options(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_finance)]):
    orders = (
        db.query(Order)
        .options(joinedload(Order.inquiry), joinedload(Order.quote))
        .filter(Order.status.in_(OPEN_ORDER_STATUSES))
        .order_by(Order.id.desc())
        .all()
    )
    pos = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
        .order_by(PurchaseOrder.id.desc())
        .all()
    )
    return {
        "orders": [{"id": o.id, "no": o.no, "customer_name": (getattr(o, "customer_name", None) or "") or (o.inquiry.customer_name if o.inquiry else ""), "total": (to_float(getattr(o, "total", 0)) or 0) or (to_float(o.quote.total) if o.quote else 0)} for o in orders],
        "purchase_orders": [{"id": p.id, "no": p.no, "supplier_name": p.supplier_name, "total": to_float(p.total)} for p in pos],
    }
