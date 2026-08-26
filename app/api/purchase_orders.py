from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.access import can_view_po, filter_purchase_orders, infer_po_purchaser_id, is_purchase_owner
from app.core.auth import ROLE_LABEL, get_current_user, require_roles
from app.db.database import get_db
from app.db.models import FinanceAllocLine, FinanceInvoice, FinancePayment, FinanceVoucher, FinanceWriteoff, Inquiry, InquiryLine, Order, OrderLog, Product, PurchaseOrder, PurchaseOrderLine, PurchaseOrderLog, Quote, User
from app.core.e2e import MoneyIn, money, to_api_money
from app.core.utils import apply_doc_date_range, fmt_dt, next_no, to_float

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase-orders"])

PO_STATUS = {
    "pending_fill": "待采购填写",
    "pending_audit": "待审核",
    "rejected": "已驳回",
    "in_progress": "进行中",
    "received": "收货",
    "inbound": "入库",
    "accepted": "验收",
    "done": "已完成",
}
PO_STEPS = ["pending_fill", "pending_audit", "in_progress", "received", "inbound", "accepted", "done"]
PO_NEXT = {"in_progress": "received", "received": "inbound", "inbound": "accepted", "accepted": "done"}
PO_WAREHOUSES = ["主仓", "原料仓", "成品仓", "退货仓", "第三方仓"]


class LineIn(BaseModel):
    product_id: Optional[int] = None
    sku: str = ""
    product_name: str = ""
    spec: str = ""
    unit: str = "pcs"
    quantity: float = Field(gt=0)
    unit_price: MoneyIn = 0
    barcode: str = ""
    model: str = ""
    line_remark: str = ""
    tax_rate: float = Field(default=0, ge=0)
    warehouse: str = ""


class PoFillIn(BaseModel):
    supplier_name: str = ""
    contact_name: str = ""
    contact_phone: str = ""
    payment_terms: str = ""
    expected_date: Optional[date] = None
    currency: str = "RMB"
    remark: str = ""
    sales_order_id: Optional[int] = None
    doc_date: Optional[date] = None
    purchaser_id: Optional[int] = None
    project: str = ""
    freight: MoneyIn = 0
    extra_tax: MoneyIn = 0
    deposit: MoneyIn = 0
    settle_method: str = ""
    pay_account: str = ""
    pay_deposit: bool = False
    supplier_bank: str = ""
    supplier_account: str = ""
    shipping_warehouse: str = ""
    lines: List[LineIn] = []


class PoCreateIn(PoFillIn):
    submit: bool = False


class AuditIn(BaseModel):
    action: str
    remark: str = ""


class LogisticsIn(BaseModel):
    logistics_company: str = ""
    tracking_no: str = ""
    comment: str = ""


def load_sales_order(db: Session, order_id: int) -> Optional[Order]:
    return (
        db.query(Order)
        .options(
            joinedload(Order.quote),
            joinedload(Order.inquiry).joinedload(Inquiry.lines).joinedload(InquiryLine.product),
            joinedload(Order.inquiry).joinedload(Inquiry.quotes),
            joinedload(Order.inquiry).joinedload(Inquiry.selected_quote),
        )
        .filter(Order.id == order_id)
        .first()
    )


def bind_adopted_quote(db: Session, order: Optional[Order]) -> None:
    if not order:
        return
    if order.quote_id and not getattr(order, "quote", None):
        order.quote = db.get(Quote, order.quote_id)
    inq = order.inquiry
    if inq and inq.selected_quote_id and not getattr(inq, "selected_quote", None):
        inq.selected_quote = db.get(Quote, inq.selected_quote_id)


def assign_po_purchaser(po: PurchaseOrder, so: Optional[Order], user: User, db: Session) -> None:
    bind_adopted_quote(db, so)
    inferred = infer_po_purchaser_id(so) if so else None
    if so and inferred and user.role == "purchase" and inferred != user.id:
        raise HTTPException(403, "该销售单采用了其他采购的报价，对应采购单仅该采购可见")
    if inferred:
        po.purchaser_id = inferred
    elif user.role == "purchase":
        po.purchaser_id = user.id


def add_lines_from_inquiry(db: Session, po: PurchaseOrder, inq: Optional[Inquiry]) -> None:
    for ln in inq.lines if inq else []:
        p = ln.product
        qty = money(to_float(ln.quantity) or 0)
        if qty <= 0:
            continue
        db.add(
            PurchaseOrderLine(
                purchase_order_id=po.id,
                product_id=ln.product_id,
                sku=(p.sku if p else "") or "",
                barcode=(p.sku if p else "") or "",
                product_name=(p.name if p else "") or ln.product_name or "",
                spec=(p.spec if p else "") or ln.spec or "",
                unit=(p.unit if p else "") or ln.unit or "pcs",
                quantity=qty,
                unit_price=0,
                amount=0,
                model="",
                line_remark="",
                tax_rate=0,
            )
        )


def apply_header(po: PurchaseOrder, body: PoFillIn, so: Optional[Order]) -> None:
    po.supplier_name = (body.supplier_name or "").strip()
    po.contact_name = (body.contact_name or "").strip()
    po.contact_phone = (body.contact_phone or "").strip()
    po.payment_terms = (body.payment_terms or "").strip()
    po.expected_date = body.expected_date
    if body.currency:
        po.currency = body.currency
    po.remark = body.remark or ""
    po.sales_order_id = so.id if so else None
    po.doc_date = body.doc_date or po.doc_date or date.today()
    po.project = (body.project or "").strip()
    po.freight = money(body.freight or 0)
    po.extra_tax = money(body.extra_tax or 0)
    po.deposit = money(body.deposit or 0)
    po.settle_method = (body.settle_method or "").strip()
    po.pay_account = (body.pay_account or "").strip()
    po.pay_deposit = bool(body.pay_deposit)
    po.supplier_bank = (body.supplier_bank or "").strip()
    po.supplier_account = (body.supplier_account or "").strip()
    po.shipping_warehouse = (body.shipping_warehouse or "").strip()


def line_amount(qty: Decimal, price: Decimal, tax_rate: Decimal = Decimal("0")) -> Decimal:
    net = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not tax_rate:
        return net
    tax = (net * tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return net + tax


def replace_lines(db: Session, po: PurchaseOrder, lines: List[LineIn]) -> Decimal:
    db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == po.id).delete()
    goods = Decimal("0.00")
    for ln in lines:
        p = db.get(Product, ln.product_id) if ln.product_id else None
        qty = money(ln.quantity)
        price = money(ln.unit_price)
        rate = money(ln.tax_rate or 0)
        amount = line_amount(qty, price, rate)
        goods += amount
        db.add(
            PurchaseOrderLine(
                purchase_order_id=po.id,
                product_id=p.id if p else None,
                sku=(p.sku if p else ln.sku) or "",
                barcode=(ln.barcode or (p.sku if p else "") or ln.sku) or "",
                product_name=(p.name if p else ln.product_name) or "",
                spec=(p.spec if p else ln.spec) or "",
                unit=(p.unit if p else ln.unit) or "pcs",
                quantity=qty,
                unit_price=price,
                amount=amount,
                model=(ln.model or "").strip(),
                line_remark=(ln.line_remark or "").strip(),
                tax_rate=rate,
                warehouse=(ln.warehouse or "").strip(),
            )
        )
    freight = money(po.freight)
    extra = money(po.extra_tax)
    total = goods + freight + extra
    if money(po.deposit) > total:
        raise HTTPException(400, "订金不能超过订单金额")
    po.total = total
    return total


def require_submit_ready(body: PoFillIn) -> None:
    if not body.expected_date:
        raise HTTPException(400, "请填写交货时间")
    if not (body.supplier_bank or "").strip():
        raise HTTPException(400, "请填写开户行")
    if not (body.supplier_account or "").strip():
        raise HTTPException(400, "请填写账号")
    if not body.lines:
        raise HTTPException(400, "至少一行明细")
    for i, ln in enumerate(body.lines, start=1):
        if not ln.product_id and not (ln.product_name or "").strip():
            raise HTTPException(400, f"第 {i} 行请填写商品")
        if not (ln.unit or "").strip():
            raise HTTPException(400, f"第 {i} 行请填写采购单位")
        if not ln.quantity or ln.quantity <= 0:
            raise HTTPException(400, f"第 {i} 行请填写数量")
        if money(ln.unit_price) < 0:
            raise HTTPException(400, f"第 {i} 行请填写单价")


def ensure_po_from_sales_order(db: Session, order: Order, user: User) -> PurchaseOrder:
    bind_adopted_quote(db, order)
    existing = db.query(PurchaseOrder).filter(PurchaseOrder.sales_order_id == order.id).first()
    if existing:
        pid = infer_po_purchaser_id(order)
        if pid:
            existing.purchaser_id = pid
        return existing
    inq = order.inquiry
    po = PurchaseOrder(
        no=next_no(db, PurchaseOrder, "PO"),
        sales_order_id=order.id,
        supplier_name="",
        currency=(inq.currency if inq else None) or getattr(order, "currency", None) or "RMB",
        remark="",
        status="pending_fill",
        creator_id=user.id,
        purchaser_id=infer_po_purchaser_id(order),
        total=0,
    )
    db.add(po)
    db.flush()
    if order.lines:
        for ln in order.lines:
            db.add(
                PurchaseOrderLine(
                    purchase_order_id=po.id,
                    product_id=ln.product_id,
                    sku=ln.sku or ln.barcode or "",
                    barcode=getattr(ln, "barcode", "") or ln.sku or "",
                    product_name=ln.product_name or "",
                    spec=ln.spec or "",
                    unit=ln.unit or "pcs",
                    quantity=ln.quantity,
                    unit_price=0,
                    amount=0,
                )
            )
    else:
        add_lines_from_inquiry(db, po, inq)
    db.add(
        PurchaseOrderLog(
            purchase_order_id=po.id,
            kind="status",
            from_status="",
            to_status="pending_fill",
            comment="销售提交合同，自动生成采购单，待采购填写",
            operator_id=user.id,
        )
    )
    return po


def serialize_po(po: PurchaseOrder, user: Optional[User] = None) -> dict:
    so = po.sales_order
    goods = Decimal("0.00")
    qty_sum = Decimal("0.00")
    for ln in po.lines:
        goods += money(ln.amount)
        qty_sum += money(ln.quantity)
    freight = money(getattr(po, "freight", 0))
    extra = money(getattr(po, "extra_tax", 0))
    deposit = money(getattr(po, "deposit", 0))
    order_amount = goods + freight + extra
    remaining = order_amount - deposit
    payable = deposit if getattr(po, "pay_deposit", False) else Decimal("0.00")
    data = {
        "id": po.id,
        "no": po.no,
        "status": po.status,
        "status_label": PO_STATUS.get(po.status, po.status),
        "supplier_name": po.supplier_name,
        "contact_name": po.contact_name or "",
        "contact_phone": po.contact_phone or "",
        "supplier_bank": getattr(po, "supplier_bank", "") or "",
        "supplier_account": getattr(po, "supplier_account", "") or "",
        "shipping_warehouse": getattr(po, "shipping_warehouse", "") or "",
        "payment_terms": po.payment_terms or "",
        "expected_date": po.expected_date.isoformat() if po.expected_date else "",
        "doc_date": po.doc_date.isoformat() if getattr(po, "doc_date", None) else (po.created_at.date().isoformat() if po.created_at else ""),
        "purchaser_id": getattr(po, "purchaser_id", None),
        "purchaser_name": po.purchaser.name if getattr(po, "purchaser", None) else "",
        "project": getattr(po, "project", "") or "",
        "freight": to_api_money(freight),
        "extra_tax": to_api_money(extra),
        "deposit": to_api_money(deposit),
        "settle_method": getattr(po, "settle_method", "") or "",
        "pay_account": getattr(po, "pay_account", "") or "",
        "pay_deposit": bool(getattr(po, "pay_deposit", False)),
        "goods_amount": to_api_money(goods),
        "order_amount": to_api_money(order_amount),
        "remaining": to_api_money(remaining),
        "payable": to_api_money(payable),
        "qty_sum": float(qty_sum),
        "sku_count": len(po.lines),
        "currency": po.currency,
        "total": to_float(po.total),
        "remark": po.remark,
        "audit_remark": po.audit_remark or "",
        "sales_order_id": po.sales_order_id,
        "sales_order_no": so.no if so else "",
        "customer_name": (getattr(so, "customer_name", None) or "") or (so.inquiry.customer_name if so and so.inquiry else ""),
        "creator_name": po.creator.name if po.creator else "",
        "created_at": fmt_dt(po.created_at),
        "updated_at": fmt_dt(po.updated_at) if po.updated_at else "",
        "can_audit": bool(user and user.role == "admin" and po.status == "pending_audit"),
        "can_fill": bool(
            user
            and user.role == "purchase"
            and po.status in ("pending_fill", "rejected")
            and is_purchase_owner(user, po)
        ),
        "can_logistics": bool(
            user and user.role == "purchase" and po.status == "in_progress" and is_purchase_owner(user, po)
        ),
        "can_advance": bool(user and user.role == "purchase" and po.status in PO_NEXT and is_purchase_owner(user, po)),
        "can_delete": bool(user and user.role == "admin"),
        "lines": [
            {
                "id": ln.id,
                "product_id": ln.product_id,
                "sku": ln.sku,
                "barcode": getattr(ln, "barcode", "") or ln.sku or "",
                "product_name": ln.product_name,
                "spec": ln.spec,
                "model": getattr(ln, "model", "") or "",
                "line_remark": getattr(ln, "line_remark", "") or "",
                "unit": ln.unit,
                "quantity": to_float(ln.quantity),
                "unit_price": to_float(ln.unit_price),
                "tax_rate": to_float(getattr(ln, "tax_rate", 0)) or 0,
                "warehouse": getattr(ln, "warehouse", "") or "",
                "amount": to_float(ln.amount),
            }
            for ln in po.lines
        ],
        "logs": [
            {
                "kind": lg.kind,
                "from_status": lg.from_status,
                "from_label": PO_STATUS.get(lg.from_status, lg.from_status),
                "to_status": lg.to_status,
                "to_label": PO_STATUS.get(lg.to_status, lg.to_status),
                "logistics_company": lg.logistics_company,
                "tracking_no": lg.tracking_no,
                "comment": lg.comment,
                "operator": lg.operator.name if lg.operator else "",
                "role_label": ROLE_LABEL.get(lg.operator.role, "") if lg.operator else "",
                "created_at": fmt_dt(lg.created_at),
            }
            for lg in sorted(po.logs, key=lambda x: x.id)
        ],
        "steps": [{"key": k, "label": PO_STATUS[k]} for k in PO_STEPS],
    }
    logi = [lg for lg in data["logs"] if lg["kind"] == "logistics"]
    data["latest_logistics"] = logi[-1] if logi else None
    return data


def load_po(db: Session, po_id: int):
    return (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.lines),
            joinedload(PurchaseOrder.creator),
            joinedload(PurchaseOrder.purchaser),
            joinedload(PurchaseOrder.logs).joinedload(PurchaseOrderLog.operator),
            joinedload(PurchaseOrder.sales_order).joinedload(Order.quote),
            joinedload(PurchaseOrder.sales_order).joinedload(Order.inquiry).joinedload(Inquiry.quotes),
            joinedload(PurchaseOrder.sales_order).joinedload(Order.inquiry).joinedload(Inquiry.selected_quote),
        )
        .filter(PurchaseOrder.id == po_id)
        .first()
    )


@router.get("")
def list_pos(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    status: str = "",
    sales_order_id: Optional[int] = None,
    date_from: str = "",
    date_to: str = "",
):
    if user.role not in ("admin", "purchase", "finance", "sales"):
        raise HTTPException(403, "没有权限")
    q = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.creator),
        joinedload(PurchaseOrder.purchaser),
        joinedload(PurchaseOrder.sales_order).joinedload(Order.inquiry),
    )
    q = filter_purchase_orders(q, user)
    if user.role == "sales" and not status:
        q = q.filter(PurchaseOrder.status.notin_(("pending_audit",)))
    if status:
        q = q.filter(PurchaseOrder.status == status)
    if sales_order_id:
        q = q.filter(PurchaseOrder.sales_order_id == sales_order_id)
    q = apply_doc_date_range(q, PurchaseOrder, date_from, date_to)
    rows = q.order_by(PurchaseOrder.id.desc()).all()
    return [
        {
            "id": r.id,
            "no": r.no,
            "supplier_name": r.supplier_name,
            "sales_order_id": r.sales_order_id,
            "sales_order_no": r.sales_order.no if r.sales_order else "",
            "customer_name": r.sales_order.inquiry.customer_name if r.sales_order and r.sales_order.inquiry else "",
            "currency": r.currency,
            "total": to_float(r.total),
            "status": r.status,
            "status_label": PO_STATUS.get(r.status, r.status),
            "purchaser_name": r.purchaser.name if getattr(r, "purchaser", None) else "",
            "creator_name": r.creator.name if r.creator else "",
            "doc_date": r.doc_date.isoformat() if getattr(r, "doc_date", None) else "",
            "created_at": fmt_dt(r.created_at),
            "can_delete": user.role == "admin",
        }
        for r in rows
    ]


@router.get("/meta")
def po_meta(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    if user.role not in ("admin", "purchase", "finance", "sales"):
        raise HTTPException(403, "没有权限")
    purchasers = db.query(User).filter(User.role == "purchase", User.is_active.is_(True)).order_by(User.id).all()
    suppliers = (
        db.query(PurchaseOrder.supplier_name)
        .filter(PurchaseOrder.supplier_name != "")
        .distinct()
        .order_by(PurchaseOrder.supplier_name)
        .all()
    )
    return {
        "today": date.today().isoformat(),
        "purchasers": [{"id": u.id, "name": u.name} for u in purchasers],
        "suppliers": [r[0] for r in suppliers if r[0]],
        "warehouses": list(PO_WAREHOUSES),
        "settle_methods": ["现金", "银行转账", "电汇", "支付宝", "微信", "支票"],
        "accounts": ["现金", "基本户", "支付宝", "微信"],
    }


@router.post("")
def create_po(
    body: PoCreateIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("purchase"))],
):
    so = load_sales_order(db, body.sales_order_id) if body.sales_order_id else None
    if body.sales_order_id and not so:
        raise HTTPException(400, "销售订单不存在")
    lines = list(body.lines)
    if body.submit:
        require_submit_ready(body)
    po = PurchaseOrder(
        no=next_no(db, PurchaseOrder, "PO"),
        status="pending_fill",
        creator_id=user.id,
        total=0,
    )
    apply_header(po, body, so)
    assign_po_purchaser(po, so, user, db)
    db.add(po)
    db.flush()
    if lines:
        replace_lines(db, po, lines)
    elif so:
        add_lines_from_inquiry(db, po, so.inquiry)
    if body.submit:
        po.status = "pending_audit"
    db.add(
        PurchaseOrderLog(
            purchase_order_id=po.id,
            kind="status",
            from_status="",
            to_status=po.status,
            comment="采购自主新建采购单并提交审核" if body.submit else "采购自主新建采购单",
            operator_id=user.id,
        )
    )
    db.commit()
    return serialize_po(load_po(db, po.id), user)


def _fill_existing(po: PurchaseOrder, body: PoFillIn, db: Session, user: User, submit: bool):
    if not is_purchase_owner(user, po):
        raise HTTPException(404, "采购单不存在")
    if po.status not in ("pending_fill", "rejected"):
        raise HTTPException(400, "当前状态不可填写")
    so = load_sales_order(db, body.sales_order_id) if body.sales_order_id else None
    if body.sales_order_id and not so:
        raise HTTPException(400, "销售订单不存在")
    if submit:
        require_submit_ready(body)
    apply_header(po, body, so)
    assign_po_purchaser(po, so, user, db)
    if body.lines:
        replace_lines(db, po, body.lines)
    elif submit:
        raise HTTPException(400, "至少一行明细")
    prev = po.status
    if submit:
        po.status = "pending_audit"
        db.add(
            PurchaseOrderLog(
                purchase_order_id=po.id,
                kind="status",
                from_status=prev,
                to_status=po.status,
                comment="采购已填写，提交管理员审核",
                operator_id=user.id,
            )
        )
    db.commit()
    return serialize_po(load_po(db, po.id), user)


@router.post("/{po_id}/save")
def save_po(
    po_id: int,
    body: PoFillIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("purchase"))],
):
    po = load_po(db, po_id)
    if not po:
        raise HTTPException(404, "采购单不存在")
    return _fill_existing(po, body, db, user, submit=False)


@router.post("/{po_id}/submit")
def submit_po(
    po_id: int,
    body: PoFillIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("purchase"))],
):
    po = load_po(db, po_id)
    if not po:
        raise HTTPException(404, "采购单不存在")
    return _fill_existing(po, body, db, user, submit=True)


@router.get("/{po_id}")
def get_po(
    po_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    po = load_po(db, po_id)
    if not po or not can_view_po(user, po):
        raise HTTPException(404, "采购单不存在")
    data = serialize_po(po, user)
    if user.role in ("admin", "finance"):
        from app.api.finance import alloc_cash_rmb, doc_currency, order_customer, order_contract
        from app.core.fx import rmb_rates, to_rmb

        vouchers = (
            db.query(FinanceVoucher)
            .join(FinanceAllocLine, FinanceAllocLine.voucher_id == FinanceVoucher.id)
            .filter(FinanceAllocLine.purchase_order_id == po.id, FinanceVoucher.direction == "payment")
            .order_by(FinanceVoucher.id.desc())
            .all()
        )
        so = po.sales_order
        rates = rmb_rates()
        paid = float(alloc_cash_rmb(db, purchase_order_id=po.id, rates=rates))
        received = float(alloc_cash_rmb(db, order_id=so.id, rates=rates)) if so else 0.0
        so_amt = float(to_rmb(order_contract(so), doc_currency(order=so), rates)) if so else 0.0
        data["payment_vouchers"] = [{"id": v.id, "no": v.no, "summary": v.summary or ""} for v in vouchers]
        data["profit"] = {
            "paid": to_api_money(paid),
            "received": to_api_money(received),
            "so_amount": to_api_money(so_amt),
            "customer_name": order_customer(so),
            "profit": to_api_money(round(received - paid, 2)),
            "unit": "RMB",
        }
    return data


@router.delete("/{po_id}")
def delete_po(
    po_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    po = load_po(db, po_id)
    if not po:
        raise HTTPException(404, "采购单不存在")
    allocs = db.query(FinanceAllocLine).filter(FinanceAllocLine.purchase_order_id == po.id).all()
    voucher_ids = {a.voucher_id for a in allocs}
    for a in allocs:
        db.delete(a)
    db.flush()
    for vid in voucher_ids:
        v = db.get(FinanceVoucher, vid)
        if v and not v.allocs:
            db.delete(v)
    db.query(FinancePayment).filter(FinancePayment.purchase_order_id == po.id).delete()
    invoices = db.query(FinanceInvoice).filter(FinanceInvoice.purchase_order_id == po.id).all()
    for inv in invoices:
        db.query(FinanceWriteoff).filter(FinanceWriteoff.invoice_id == inv.id).delete()
        db.delete(inv)
    db.delete(po)
    db.commit()
    return {"ok": True, "message": "采购单已删除"}


@router.post("/{po_id}/audit")
def audit_po(
    po_id: int,
    body: AuditIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("admin"))],
):
    po = load_po(db, po_id)
    if not po:
        raise HTTPException(404, "采购单不存在")
    if po.status != "pending_audit":
        raise HTTPException(400, "当前不是待审核")
    po.audit_remark = (body.remark or "").strip()
    if body.action == "pass":
        po.status = "in_progress"
        db.add(
            PurchaseOrderLog(
                purchase_order_id=po.id,
                kind="status",
                from_status="pending_audit",
                to_status="in_progress",
                comment=po.audit_remark or "审核通过，采购单生效",
                operator_id=user.id,
            )
        )
        from app.api.finance import ensure_payment_voucher_for_po

        ensure_payment_voucher_for_po(db, po, user)
        db.commit()
        return serialize_po(load_po(db, po.id), user)
    if body.action == "reject":
        po.status = "pending_fill"
        db.add(
            PurchaseOrderLog(
                purchase_order_id=po.id,
                kind="status",
                from_status="pending_audit",
                to_status="pending_fill",
                comment=po.audit_remark or "审核驳回，请采购修改后重新提交",
                operator_id=user.id,
            )
        )
        db.commit()
        return serialize_po(load_po(db, po.id), user)
    raise HTTPException(400, "action 仅为 pass 或 reject")


@router.post("/{po_id}/logistics")
def update_logistics(
    po_id: int,
    body: LogisticsIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("purchase"))],
):
    po = load_po(db, po_id)
    if not po or not is_purchase_owner(user, po):
        raise HTTPException(404, "采购单不存在")
    if po.status != "in_progress":
        raise HTTPException(400, "仅进行中可更新物流")
    if not (body.logistics_company or body.tracking_no or body.comment):
        raise HTTPException(400, "请填写物流信息或说明")
    db.add(
        PurchaseOrderLog(
            purchase_order_id=po.id,
            kind="logistics",
            from_status="in_progress",
            to_status="in_progress",
            logistics_company=body.logistics_company.strip(),
            tracking_no=body.tracking_no.strip(),
            comment=body.comment.strip() or "更新物流",
            operator_id=user.id,
        )
    )
    db.commit()
    return serialize_po(load_po(db, po.id), user)


@router.post("/{po_id}/advance")
def advance_po(
    po_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    po = load_po(db, po_id)
    if not po or user.role != "purchase" or not is_purchase_owner(user, po):
        raise HTTPException(404, "采购单不存在")
    nxt = PO_NEXT.get(po.status)
    if not nxt:
        raise HTTPException(400, "当前状态不可推进")
    labels = {"received": "确认收货", "inbound": "确认入库", "accepted": "确认验收", "done": "验收成功"}
    prev = po.status
    po.status = nxt
    db.add(
        PurchaseOrderLog(
            purchase_order_id=po.id,
            kind="status",
            from_status=prev,
            to_status=nxt,
            comment=labels.get(nxt, nxt),
            operator_id=user.id,
        )
    )
    if nxt == "done" and po.sales_order_id:
        leftover = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.sales_order_id == po.sales_order_id,
                PurchaseOrder.id != po.id,
                PurchaseOrder.status != "done",
            )
            .first()
        )
        so = po.sales_order
        if so and not leftover and so.status == "fulfilling":
            so.status = "done"
            db.add(
                OrderLog(
                    order_id=so.id,
                    from_status="fulfilling",
                    to_status="done",
                    operator_id=user.id,
                    comment="采购验收成功，销售订单完成",
                )
            )
    db.commit()
    return serialize_po(load_po(db, po.id), user)
