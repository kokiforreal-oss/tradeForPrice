from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.access import can_view_order, filter_orders, is_sales_owner
from app.core.auth import ROLE_LABEL, get_current_user, require_roles
from app.db.database import get_db
from app.db.models import Inquiry, InquiryLine, Order, OrderLine, OrderLog, Product, Quote, User
from app.api.purchase_orders import ensure_po_from_sales_order
from app.core.e2e import MoneyIn, money, to_api_money
from app.core.utils import fmt_dt, next_no, to_float

router = APIRouter(prefix="/api/orders", tags=["orders"])

INCOTERMS = ("EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")

STEPS = ["pending_audit", "contract", "fulfilling", "done"]
STEP_LABEL = {
    "pending_audit": "待审核",
    "rejected": "已驳回",
    "draft": "草稿",
    "contract": "待填合同",
    "fulfilling": "履约中",
    "done": "完成",
    "payment": "收款",
    "production": "工厂生产",
    "shipping": "运输",
    "balance": "尾款",
}
VISIBLE_STATUSES = ("contract", "fulfilling", "done", "payment", "production", "shipping", "balance")


class AuditIn(BaseModel):
    action: str
    remark: str = ""


class SoLineIn(BaseModel):
    product_id: Optional[int] = None
    sku: str = ""
    barcode: str = ""
    product_name: str = ""
    spec: str = ""
    model: str = ""
    line_remark: str = ""
    unit: str = "pcs"
    quantity: float = Field(gt=0)
    unit_price: MoneyIn = 0
    tax_rate: float = Field(default=0, ge=0)
    supplier_name: str = ""
    is_gift: bool = False


class SoFillIn(BaseModel):
    voucher_type: str = "sale"
    customer_name: str = ""
    customer_country: str = ""
    currency: str = "RMB"
    doc_date: Optional[date] = None
    project: str = ""
    salesperson_id: Optional[int] = None
    expected_date: Optional[date] = None
    header_tax_rate: float = 0
    order_remark: str = ""
    incoterm: str = ""
    loading_port: str = ""
    destination_port: str = ""
    freight: MoneyIn = 0
    extra_tax: MoneyIn = 0
    deposit: MoneyIn = 0
    settle_method: str = ""
    pay_account: str = ""
    pay_deposit: bool = False
    lines: List[SoLineIn] = []


class SoCreateIn(SoFillIn):
    submit: bool = False


def line_amount(qty: Decimal, price: Decimal, tax_rate: Decimal, is_gift: bool) -> Decimal:
    if is_gift:
        return Decimal("0.00")
    net = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax = (net * tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return net + tax


def serialize_order(order: Order, user: Optional[User] = None) -> dict:
    inq = order.inquiry
    quote = order.quote
    lines = []
    if order.lines:
        for ln in order.lines:
            lines.append(
                {
                    "id": ln.id,
                    "product_id": ln.product_id,
                    "sku": ln.sku,
                    "barcode": ln.barcode or ln.sku or "",
                    "product_name": ln.product_name,
                    "spec": ln.spec,
                    "model": ln.model or "",
                    "line_remark": ln.line_remark or "",
                    "unit": ln.unit,
                    "quantity": to_float(ln.quantity),
                    "unit_price": to_float(ln.unit_price),
                    "tax_rate": to_float(ln.tax_rate) or 0,
                    "amount": to_float(ln.amount),
                    "supplier_name": ln.supplier_name or "",
                    "is_gift": bool(ln.is_gift),
                }
            )
    elif inq:
        price_map = {ql.inquiry_line_id: ql for ql in (quote.lines if quote else [])}
        for ln in inq.lines:
            ql = price_map.get(ln.id)
            p = ln.product
            lines.append(
                {
                    "product_id": ln.product_id,
                    "sku": p.sku if p else "",
                    "barcode": (p.sku if p else "") or "",
                    "product_name": (p.name if p else "") or getattr(ln, "product_name", "") or "",
                    "spec": (p.spec if p else "") or getattr(ln, "spec", "") or "",
                    "model": "",
                    "line_remark": "",
                    "unit": (p.unit if p else "") or getattr(ln, "unit", "") or "",
                    "quantity": to_float(ln.quantity),
                    "unit_price": to_float(ql.unit_price) if ql else None,
                    "tax_rate": 0,
                    "amount": to_float(ql.amount) if ql else None,
                    "supplier_name": "",
                    "is_gift": False,
                }
            )
    goods = sum((money(l.get("amount") or 0) for l in lines), Decimal("0.00"))
    freight = money(getattr(order, "freight", 0))
    extra = money(getattr(order, "extra_tax", 0))
    deposit = money(getattr(order, "deposit", 0))
    order_amount = goods + freight + extra
    remaining = order_amount - deposit
    customer = (getattr(order, "customer_name", None) or "") or (inq.customer_name if inq else "")
    currency = (getattr(order, "currency", None) or "") or (inq.currency if inq else "RMB")
    sales_name = ""
    if getattr(order, "salesperson", None):
        sales_name = order.salesperson.name
    elif inq and inq.creator:
        sales_name = inq.creator.name
    elif order.creator:
        sales_name = order.creator.name
    quote_total = to_api_money(quote.total) if quote else to_api_money(order_amount)
    owner = bool(user and user.role == "sales" and is_sales_owner(user, order))
    return {
        "id": order.id,
        "no": order.no,
        "status": order.status,
        "status_label": STEP_LABEL.get(order.status, order.status),
        "voucher_type": getattr(order, "voucher_type", "sale") or "sale",
        "inquiry_id": inq.id if inq else None,
        "inquiry_no": inq.no if inq else "",
        "customer_name": customer,
        "customer_country": getattr(order, "customer_country", "") or "",
        "currency": currency,
        "quote_total": quote_total,
        "sales_name": sales_name,
        "salesperson_id": getattr(order, "salesperson_id", None),
        "doc_date": order.doc_date.isoformat() if getattr(order, "doc_date", None) else (order.created_at.date().isoformat() if order.created_at else ""),
        "project": getattr(order, "project", "") or "",
        "expected_date": order.expected_date.isoformat() if getattr(order, "expected_date", None) else "",
        "header_tax_rate": to_float(getattr(order, "header_tax_rate", 0)) or 0,
        "order_remark": getattr(order, "order_remark", "") or "",
        "freight": to_api_money(freight),
        "extra_tax": to_api_money(extra),
        "deposit": to_api_money(deposit),
        "settle_method": getattr(order, "settle_method", "") or "",
        "pay_account": getattr(order, "pay_account", "") or "",
        "pay_deposit": bool(getattr(order, "pay_deposit", False)),
        "goods_amount": to_api_money(goods),
        "order_amount": to_api_money(order_amount),
        "remaining": to_api_money(remaining),
        "payable": to_api_money(deposit if getattr(order, "pay_deposit", False) else 0),
        "sku_count": len(lines),
        "incoterm": order.incoterm or "",
        "loading_port": order.loading_port or "",
        "destination_port": order.destination_port or "",
        "payment_terms": order.payment_terms or "",
        "factory_address": order.factory_address or "",
        "audit_remark": order.audit_remark or "",
        "contract_no": order.contract_no,
        "contract_date": order.contract_date.isoformat() if order.contract_date else None,
        "contract_remark": order.contract_remark,
        "contract_file": order.contract_file,
        "created_at": fmt_dt(order.created_at),
        "updated_at": fmt_dt(order.updated_at) if order.updated_at else "",
        "incoterms": list(INCOTERMS),
        "can_audit": bool(user and user.role == "admin" and order.status == "pending_audit"),
        "can_fill": bool(owner and order.status == "draft"),
        "can_save": bool(owner and order.status in ("draft", "contract")),
        "lines": lines,
        "purchase_orders": [
            {"id": p.id, "no": p.no, "status": p.status, "supplier_name": p.supplier_name, "total": to_float(p.total)}
            for p in (order.purchase_orders or [])
            if not user or user.role != "purchase" or p.purchaser_id == user.id
        ],
        "logs": [
            {
                "from_status": lg.from_status,
                "from_label": STEP_LABEL.get(lg.from_status, lg.from_status),
                "to_status": lg.to_status,
                "to_label": STEP_LABEL.get(lg.to_status, lg.to_status),
                "operator": lg.operator.name if lg.operator else "",
                "role_label": ROLE_LABEL.get(lg.operator.role, "") if lg.operator else "",
                "comment": lg.comment,
                "created_at": fmt_dt(lg.created_at),
            }
            for lg in sorted(order.logs, key=lambda x: x.id)
        ],
        "steps": [{"key": k, "label": STEP_LABEL[k]} for k in STEPS],
    }


def load_order(db: Session, order_id: int):
    return (
        db.query(Order)
        .options(
            joinedload(Order.inquiry).joinedload(Inquiry.lines).joinedload(InquiryLine.product),
            joinedload(Order.inquiry).joinedload(Inquiry.creator),
            joinedload(Order.quote).joinedload(Quote.lines),
            joinedload(Order.lines),
            joinedload(Order.creator),
            joinedload(Order.salesperson),
            joinedload(Order.logs).joinedload(OrderLog.operator),
            joinedload(Order.purchase_orders),
        )
        .filter(Order.id == order_id)
        .first()
    )


@router.get("")
def list_orders(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    status: str = "",
):
    q = db.query(Order).options(
        joinedload(Order.inquiry).joinedload(Inquiry.creator),
        joinedload(Order.salesperson),
        joinedload(Order.creator),
    )
    q = filter_orders(q, user)
    if user.role == "sales" and not status:
        q = q.filter(Order.status.in_(VISIBLE_STATUSES + ("draft", "pending_audit")))
    if status:
        q = q.filter(Order.status == status)
    rows = q.order_by(Order.id.desc()).all()
    return [
        {
            "id": r.id,
            "no": r.no,
            "inquiry_no": r.inquiry.no if r.inquiry else "",
            "customer_name": (r.customer_name or "") or (r.inquiry.customer_name if r.inquiry else ""),
            "currency": (r.currency or "") or (r.inquiry.currency if r.inquiry else ""),
            "total": to_float(getattr(r, "total", 0)) or 0,
            "doc_date": r.doc_date.isoformat() if getattr(r, "doc_date", None) else "",
            "status": r.status,
            "status_label": STEP_LABEL.get(r.status, r.status),
            "sales_name": (r.salesperson.name if getattr(r, "salesperson", None) else "")
            or (r.inquiry.creator.name if r.inquiry and r.inquiry.creator else "")
            or (r.creator.name if r.creator else ""),
            "created_at": fmt_dt(r.created_at),
        }
        for r in rows
    ]


@router.get("/meta")
def order_meta(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    salespeople = db.query(User).filter(User.role == "sales", User.is_active.is_(True)).order_by(User.id).all()
    customers = (
        db.query(Order.customer_name)
        .filter(Order.customer_name != "")
        .distinct()
        .all()
    )
    from_inq = db.query(Inquiry.customer_name).distinct().all()
    names = sorted({*(r[0] for r in customers if r[0]), *(r[0] for r in from_inq if r[0])})
    return {
        "today": date.today().isoformat(),
        "salespeople": [{"id": u.id, "name": u.name} for u in salespeople],
        "customers": names,
        "settle_methods": ["现金", "银行转账", "电汇", "支付宝", "微信", "支票"],
        "accounts": ["现金", "基本户", "支付宝", "微信"],
    }


@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    order = load_order(db, order_id)
    if not order or not can_view_order(user, order):
        raise HTTPException(404, "销售订单不存在")
    return serialize_order(order, user)


def seed_order_lines(db: Session, order: Order, inq: Inquiry, quote: Optional[Quote]) -> None:
    if order.lines:
        return
    price_map = {ql.inquiry_line_id: ql for ql in (quote.lines if quote else [])}
    goods = Decimal("0.00")
    for ln in inq.lines:
        ql = price_map.get(ln.id)
        p = ln.product
        qty = money(to_float(ln.quantity) or 0)
        price = money(to_float(ql.unit_price) if ql else 0)
        amt = line_amount(qty, price, Decimal("0"), False)
        goods += amt
        db.add(
            OrderLine(
                order_id=order.id,
                product_id=ln.product_id,
                sku=(p.sku if p else "") or "",
                barcode=(p.sku if p else "") or "",
                product_name=(p.name if p else "") or getattr(ln, "product_name", "") or "",
                spec=(p.spec if p else "") or getattr(ln, "spec", "") or "",
                unit=(p.unit if p else "") or getattr(ln, "unit", "") or "pcs",
                quantity=qty,
                unit_price=price,
                tax_rate=0,
                amount=amt,
            )
        )
    order.customer_name = inq.customer_name
    order.currency = inq.currency or "RMB"
    order.creator_id = inq.creator_id
    order.salesperson_id = inq.creator_id
    order.doc_date = date.today()
    order.total = goods


def apply_so_header(order: Order, body: SoFillIn, user: User) -> None:
    if body.voucher_type not in ("sale", "return"):
        raise HTTPException(400, "类型仅为销售或退货")
    order.voucher_type = body.voucher_type
    order.customer_name = (body.customer_name or "").strip()
    order.customer_country = (body.customer_country or "").strip()
    order.currency = body.currency or "RMB"
    order.doc_date = body.doc_date or order.doc_date or date.today()
    order.project = (body.project or "").strip()
    order.salesperson_id = body.salesperson_id or order.salesperson_id or user.id
    order.expected_date = body.expected_date
    order.header_tax_rate = money(body.header_tax_rate or 0)
    order.order_remark = (body.order_remark or "").strip()
    if body.incoterm:
        order.incoterm = body.incoterm.strip().upper()
    if body.loading_port is not None:
        order.loading_port = (body.loading_port or "").strip()
    if body.destination_port is not None:
        order.destination_port = (body.destination_port or "").strip()
    order.freight = money(body.freight or 0)
    order.extra_tax = money(body.extra_tax or 0)
    order.deposit = money(body.deposit or 0)
    order.settle_method = (body.settle_method or "").strip()
    order.pay_account = (body.pay_account or "").strip()
    order.pay_deposit = bool(body.pay_deposit)


def replace_so_lines(db: Session, order: Order, lines: List[SoLineIn]) -> Decimal:
    db.query(OrderLine).filter(OrderLine.order_id == order.id).delete()
    goods = Decimal("0.00")
    for ln in lines:
        p = db.get(Product, ln.product_id) if ln.product_id else None
        qty = money(ln.quantity)
        price = money(ln.unit_price)
        rate = money(ln.tax_rate or 0)
        gift = bool(ln.is_gift)
        amt = line_amount(qty, price, rate, gift)
        goods += amt
        db.add(
            OrderLine(
                order_id=order.id,
                product_id=p.id if p else None,
                sku=(p.sku if p else ln.sku) or "",
                barcode=(ln.barcode or (p.sku if p else "") or ln.sku) or "",
                product_name=(p.name if p else ln.product_name) or "",
                spec=(p.spec if p else ln.spec) or "",
                model=(ln.model or "").strip(),
                line_remark=(ln.line_remark or "").strip(),
                unit=(p.unit if p else ln.unit) or "pcs",
                quantity=qty,
                unit_price=price,
                tax_rate=rate,
                amount=amt,
                supplier_name=(ln.supplier_name or "").strip(),
                is_gift=gift,
            )
        )
    total = goods + money(order.freight) + money(order.extra_tax)
    if money(order.deposit) > total:
        raise HTTPException(400, "订金不能超过订单金额")
    order.total = total
    return total


@router.post("")
def create_sales_order(
    body: SoCreateIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    lines = list(body.lines)
    if body.submit:
        if not (body.customer_name or "").strip():
            raise HTTPException(400, "请填写客户")
        if not lines:
            raise HTTPException(400, "至少一行明细")
    order = Order(
        no=next_no(db, Order, "SO"),
        status="draft",
        creator_id=user.id,
        inquiry_id=None,
        quote_id=None,
        total=0,
    )
    apply_so_header(order, body, user)
    db.add(order)
    db.flush()
    replace_so_lines(db, order, lines)
    if body.submit:
        order.status = "pending_audit"
    db.add(
        OrderLog(
            order_id=order.id,
            from_status="",
            to_status=order.status,
            operator_id=user.id,
            comment="提交管理员审核" if body.submit else "新建销售订单草稿",
        )
    )
    db.commit()
    return serialize_order(load_order(db, order.id), user)


@router.post("/{order_id}/save")
def save_sales_order(
    order_id: int,
    body: SoFillIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    order = load_order(db, order_id)
    if not order or not is_sales_owner(user, order):
        raise HTTPException(404, "销售订单不存在")
    if order.status not in ("draft", "contract"):
        raise HTTPException(400, "当前状态不可改单")
    apply_so_header(order, body, user)
    if body.lines:
        replace_so_lines(db, order, body.lines)
    db.commit()
    return serialize_order(load_order(db, order.id), user)


@router.post("/{order_id}/submit")
def submit_sales_order(
    order_id: int,
    body: SoFillIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
):
    order = load_order(db, order_id)
    if not order or not is_sales_owner(user, order):
        raise HTTPException(404, "销售订单不存在")
    if order.status != "draft":
        raise HTTPException(400, "仅草稿可提交审核")
    if not (body.customer_name or "").strip():
        raise HTTPException(400, "请填写客户")
    if not body.lines:
        raise HTTPException(400, "至少一行明细")
    apply_so_header(order, body, user)
    replace_so_lines(db, order, body.lines)
    prev = order.status
    order.status = "pending_audit"
    db.add(
        OrderLog(
            order_id=order.id,
            from_status=prev,
            to_status="pending_audit",
            operator_id=user.id,
            comment="提交管理员审核",
        )
    )
    db.commit()
    return serialize_order(load_order(db, order.id), user)


@router.post("/{order_id}/audit")
def audit_order(
    order_id: int,
    body: AuditIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("admin"))],
):
    order = load_order(db, order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "pending_audit":
        raise HTTPException(400, "当前不是待审核")
    action = (body.action or "").strip()
    order.audit_remark = (body.remark or "").strip()
    if action == "pass":
        order.status = "contract"
        db.add(
            OrderLog(
                order_id=order.id,
                from_status="pending_audit",
                to_status="contract",
                operator_id=user.id,
                comment=order.audit_remark or "审核通过，进入销售订单",
            )
        )
        db.commit()
        return serialize_order(load_order(db, order.id), user)
    if action == "reject":
        if not order.audit_remark:
            raise HTTPException(400, "请填写驳回原因")
        inq = order.inquiry
        order_no = order.no
        remark = order.audit_remark
        db.delete(order)
        db.flush()
        if inq:
            inq.status = "selling"
            inq.audit_reject_remark = remark
            inq.audit_reject_order_no = order_no
        db.commit()
        return {"ok": True, "action": "rejected", "message": "已驳回，销售可在询价单查看原因并重新提交"}
    raise HTTPException(400, "action 仅为 pass 或 reject")


@router.post("/{order_id}/submit-contract")
async def submit_contract(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles("sales"))],
    contract_no: str = Form(...),
    contract_date: str = Form(...),
    incoterm: str = Form(...),
    customer_country: str = Form(""),
    loading_port: str = Form(""),
    destination_port: str = Form(""),
    payment_terms: str = Form(""),
    factory_address: str = Form(""),
    contract_remark: str = Form(""),
):
    order = load_order(db, order_id)
    if not order or not can_view_order(user, order):
        raise HTTPException(404, "订单不存在")
    if order.status != "contract":
        raise HTTPException(400, "当前不是合同阶段")
    if not is_sales_owner(user, order):
        raise HTTPException(403, "没有权限")
    term = (incoterm or "").strip().upper()
    if term not in INCOTERMS:
        raise HTTPException(400, "请选择交易方式，如 FOB / CIF")
    if not customer_country.strip():
        raise HTTPException(400, "请填写客户国家")
    if not destination_port.strip():
        raise HTTPException(400, "请填写目标港口")
    if term in ("FOB", "CFR", "CIF", "FCA") and not loading_port.strip():
        raise HTTPException(400, "该交易方式需填写装运港")
    if term in ("CIF", "CFR", "CIP", "CPT", "DAP", "DPU", "DDP") and not destination_port.strip():
        raise HTTPException(400, "该交易方式需填写目标港口")
    if term == "EXW" and not factory_address.strip():
        raise HTTPException(400, "EXW 需填写工厂/仓库地址")
    try:
        d = date.fromisoformat(contract_date)
    except ValueError:
        raise HTTPException(400, "合同日期格式错误")
    order.contract_no = contract_no.strip()
    order.contract_date = d
    order.incoterm = term
    order.customer_country = customer_country.strip()
    order.loading_port = loading_port.strip()
    order.destination_port = destination_port.strip()
    order.payment_terms = payment_terms.strip()
    order.factory_address = factory_address.strip()
    order.contract_remark = contract_remark
    order.status = "fulfilling"
    inq = order.inquiry or db.get(Inquiry, order.inquiry_id)
    if inq:
        inq.status = "won"
    db.add(
        OrderLog(
            order_id=order.id,
            from_status="contract",
            to_status="fulfilling",
            operator_id=user.id,
            comment=f"提交{term}合同 {order.contract_no}，已生成采购单待采购填写",
        )
    )
    ensure_po_from_sales_order(db, order, user)
    db.commit()
    return serialize_order(load_order(db, order.id), user)


@router.delete("/{order_id}")
def delete_order(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    order = load_order(db, order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    inq = order.inquiry
    db.delete(order)
    if inq and inq.status == "won":
        inq.status = "selling"
    db.commit()
    return {"ok": True, "message": "订单已删除"}
