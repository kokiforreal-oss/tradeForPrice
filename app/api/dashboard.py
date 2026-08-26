from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.access import filter_inquiries, filter_orders, filter_purchase_orders
from app.core.auth import get_current_user
from app.db.database import get_db
from app.db.models import FinanceAllocLine, FinanceVoucher, Inquiry, Order, PurchaseOrder, User
from app.core.utils import fmt_dt

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

TODO_LIMIT = 20


def _todo(
    kind: str,
    title: str,
    href: str,
    tag: str,
    subtitle: str = "",
    time: Optional[str] = None,
) -> dict:
    return {
        "kind": kind,
        "title": title,
        "href": href,
        "tag": tag,
        "subtitle": subtitle,
        "time": time or "",
    }


def build_todos(db: Session, user: User) -> List[dict]:
    items: list[dict] = []
    if user.role == "admin":
        for o in (
            db.query(Order)
            .options(joinedload(Order.inquiry))
            .filter(Order.status == "pending_audit")
            .order_by(Order.updated_at.desc(), Order.id.desc())
            .limit(TODO_LIMIT)
            .all()
        ):
            customer = (o.customer_name or "") or (o.inquiry.customer_name if o.inquiry else "")
            items.append(
                _todo(
                    "audit",
                    f"审核销售订单 {o.no}",
                    f"#/orders/{o.id}",
                    "待审核",
                    customer or "待核对客户",
                    fmt_dt(o.updated_at or o.created_at),
                )
            )
        for po in (
            db.query(PurchaseOrder)
            .filter(PurchaseOrder.status == "pending_audit")
            .order_by(PurchaseOrder.updated_at.desc(), PurchaseOrder.id.desc())
            .limit(TODO_LIMIT)
            .all()
        ):
            items.append(
                _todo(
                    "audit",
                    f"审核采购订单 {po.no}",
                    f"#/purchase-orders/{po.id}",
                    "待审核",
                    po.supplier_name or "待核对供应商",
                    fmt_dt(po.updated_at or po.created_at),
                )
            )
    elif user.role == "sales":
        for inq in (
            db.query(Inquiry)
            .filter(Inquiry.creator_id == user.id, Inquiry.status == "quoted")
            .order_by(Inquiry.updated_at.desc(), Inquiry.id.desc())
            .limit(TODO_LIMIT)
            .all()
        ):
            items.append(
                _todo(
                    "quoted",
                    f"处理已报价询价单 {inq.no}",
                    f"#/inquiries/{inq.id}",
                    "已报价",
                    inq.customer_name or "请选择报价或继续跟进",
                    fmt_dt(inq.updated_at or inq.created_at),
                )
            )
        for inq in (
            db.query(Inquiry)
            .filter(
                Inquiry.creator_id == user.id,
                Inquiry.status == "selling",
                or_(Inquiry.audit_reject_remark != "", Inquiry.audit_reject_order_no != ""),
            )
            .order_by(Inquiry.updated_at.desc(), Inquiry.id.desc())
            .limit(TODO_LIMIT)
            .all()
        ):
            reason = (inq.audit_reject_remark or "").strip()
            items.append(
                _todo(
                    "reject",
                    f"处理被驳回订单 {inq.audit_reject_order_no or inq.no}",
                    f"#/inquiries/{inq.id}",
                    "已驳回",
                    f"原因：{reason}" if reason else (inq.customer_name or "请修改后重新提交审核"),
                    fmt_dt(inq.updated_at or inq.created_at),
                )
            )
        q = filter_orders(db.query(Order).options(joinedload(Order.inquiry)), user)
        for o in (
            q.filter(Order.status == "contract")
            .order_by(Order.updated_at.desc(), Order.id.desc())
            .limit(TODO_LIMIT)
            .all()
        ):
            customer = (o.customer_name or "") or (o.inquiry.customer_name if o.inquiry else "")
            items.append(
                _todo(
                    "contract",
                    f"填写销售合同 {o.no}",
                    f"#/orders/{o.id}",
                    "待填合同",
                    customer or "待补充客户与港口",
                    fmt_dt(o.updated_at or o.created_at),
                )
            )
    elif user.role == "purchase":
        for inq in (
            db.query(Inquiry)
            .filter(Inquiry.status == "pending_quote")
            .order_by(Inquiry.updated_at.desc(), Inquiry.id.desc())
            .limit(TODO_LIMIT)
            .all()
        ):
            items.append(
                _todo(
                    "quote",
                    f"询价待报价 {inq.no}",
                    f"#/inquiries/{inq.id}",
                    "待报价",
                    inq.customer_name or "待报价",
                    fmt_dt(inq.updated_at or inq.created_at),
                )
            )
        for po in (
            filter_purchase_orders(db.query(PurchaseOrder), user)
            .filter(PurchaseOrder.status.in_(("pending_fill", "rejected")))
            .order_by(PurchaseOrder.updated_at.desc(), PurchaseOrder.id.desc())
            .limit(TODO_LIMIT)
            .all()
        ):
            reason = (po.audit_remark or "").strip()
            rejected = po.status == "rejected" or bool(reason)
            tag = "已驳回" if rejected else "待填写"
            title = f"修改被驳回的采购单 {po.no}" if rejected else f"填写采购单 {po.no}"
            items.append(
                _todo(
                    "reject" if rejected else "fill",
                    title,
                    f"#/purchase-orders/{po.id}",
                    tag,
                    (f"原因：{reason}" if rejected and reason else "")
                    or po.supplier_name
                    or "待填写供应商与采购价",
                    fmt_dt(po.updated_at or po.created_at),
                )
            )
    elif user.role == "finance":
        po_skip = ("pending_fill", "pending_audit", "rejected")
        q = (
            db.query(FinanceVoucher)
            .options(joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.purchase_order))
            .join(FinanceAllocLine, FinanceAllocLine.voucher_id == FinanceVoucher.id)
            .outerjoin(PurchaseOrder, FinanceAllocLine.purchase_order_id == PurchaseOrder.id)
            .filter(
                FinanceVoucher.direction == "payment",
                FinanceVoucher.status == "pending",
                or_(PurchaseOrder.id.is_(None), ~PurchaseOrder.status.in_(po_skip)),
            )
            .order_by(FinanceVoucher.created_at.desc(), FinanceVoucher.id.desc())
            .limit(TODO_LIMIT)
        )
        seen = set()
        for v in q.all():
            if v.id in seen:
                continue
            seen.add(v.id)
            po_no = next((a.purchase_order.no for a in (v.allocs or []) if a.purchase_order), "")
            items.append(
                _todo(
                    "fill",
                    f"填写付款单 {v.no}",
                    f"#/finance/payments/{v.id}",
                    "待填写",
                    (f"关联 {po_no}" if po_no else "") or v.partner_name or v.summary or "采购审核通过，请登记付款",
                    fmt_dt(v.created_at),
                )
            )
    items.sort(key=lambda x: x.get("time") or "", reverse=True)
    return items[:TODO_LIMIT]


@router.get("")
def dashboard(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    inq = filter_inquiries(db.query(Inquiry), user)
    orders = filter_orders(db.query(Order), user)
    cards = []
    if user.role in ("admin", "sales", "purchase"):
        q = inq
        cards.append({"key": "pending_quote", "label": "待报价询价", "count": q.filter(Inquiry.status == "pending_quote").count()})
        cards.append({"key": "quoted", "label": "已报价询价", "count": q.filter(Inquiry.status == "quoted").count()})
    if user.role in ("admin", "sales"):
        cards.append({"key": "selling", "label": "销售中", "count": inq.filter(Inquiry.status == "selling").count()})
        cards.append({"key": "done", "label": "已完成", "count": inq.filter(Inquiry.status.in_(("won", "closed"))).count()})
    if user.role == "admin":
        cards.append({"key": "pending_audit", "label": "待审销售单", "count": db.query(Order).filter(Order.status == "pending_audit").count()})
    if user.role in ("admin", "sales", "finance"):
        cards.append({"key": "contract", "label": "待填合同", "count": orders.filter(Order.status == "contract").count()})
        cards.append({"key": "fulfilling", "label": "履约中", "count": orders.filter(Order.status == "fulfilling").count()})
    if user.role in ("admin", "finance"):
        pending_pay = (
            db.query(FinanceVoucher)
            .filter(FinanceVoucher.direction == "payment", FinanceVoucher.status == "pending")
            .count()
        )
        cards.append({"key": "pay_fill", "label": "待填付款单", "count": pending_pay})
    if user.role in ("admin", "purchase"):
        pos = filter_purchase_orders(db.query(PurchaseOrder), user)
        cards.append({"key": "po_fill", "label": "待填采购单", "count": pos.filter(PurchaseOrder.status == "pending_fill").count()})
        cards.append({"key": "po_pending", "label": "待审采购单", "count": pos.filter(PurchaseOrder.status == "pending_audit").count()})
        cards.append({"key": "po_progress", "label": "采购进行中", "count": pos.filter(PurchaseOrder.status == "in_progress").count()})
    return {
        "name": user.name,
        "role": user.role,
        "cards": cards,
        "todos": build_todos(db, user),
    }
