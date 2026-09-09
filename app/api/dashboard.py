from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.access import filter_inquiries, filter_orders, filter_purchase_orders
from app.core.auth import get_current_user
from app.db.database import get_db
from app.db.models import Feedback, FinanceAllocLine, FinanceVoucher, Inquiry, Order, PurchaseOrder, User
from app.core.utils import fmt_dt

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

PO_ADVANCE_STATUSES = (
    "in_progress",
    "stuffed",
    "domestic_inbound",
    "domestic_accepted",
    "overseas_transit",
    "inbound",
    "accepted",
)
PO_ADVANCE_TAG = {
    "in_progress": "待运输",
    "stuffed": "待入库",
    "domestic_inbound": "待验货",
    "domestic_accepted": "待运输",
    "overseas_transit": "待入库",
    "inbound": "待验货",
    "accepted": "待完成",
}


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
        "level": "high" if kind in ("audit", "reject") else "normal",
    }


def build_todos(db: Session, user: User) -> List[dict]:
    items: list[dict] = []
    if user.role == "admin":
        for inq in (
            db.query(Inquiry)
            .filter(Inquiry.status == "pending_quote")
            .order_by(Inquiry.updated_at.desc(), Inquiry.id.desc())
            .all()
        ):
            items.append(
                _todo(
                    "quote",
                    f"跟进待报价询价单 {inq.no}",
                    f"#/inquiries/{inq.id}",
                    "待报价",
                    inq.customer_name or "待采购或管理员报价",
                    fmt_dt(inq.updated_at or inq.created_at),
                )
            )
        for o in (
            db.query(Order)
            .options(joinedload(Order.inquiry))
            .filter(Order.status == "pending_audit")
            .order_by(Order.updated_at.desc(), Order.id.desc())
            .all()
        ):
            customer = (o.customer_name or "") or (o.inquiry.customer_name if o.inquiry else "")
            items.append(
                _todo(
                    "audit",
                    f"审核销售订单 {o.no}",
                    f"#/orders/{o.id}",
                    "待审核销售单",
                    customer or "待核对客户",
                    fmt_dt(o.updated_at or o.created_at),
                )
            )
        for po in (
            db.query(PurchaseOrder)
            .filter(PurchaseOrder.status == "pending_audit")
            .order_by(PurchaseOrder.updated_at.desc(), PurchaseOrder.id.desc())
            .all()
        ):
            items.append(
                _todo(
                    "audit",
                    f"审核采购订单 {po.no}",
                    f"#/purchase-orders/{po.id}",
                    "待审核采购单",
                    po.supplier_name or "待核对供应商",
                    fmt_dt(po.updated_at or po.created_at),
                )
            )
        for fb in (
            db.query(Feedback)
            .filter(Feedback.status == "open")
            .order_by(Feedback.id.desc())
            .all()
        ):
            items.append(
                _todo(
                    "audit",
                    f"处理问题反馈 {fb.no}",
                    "#/feedback?status=open",
                    "待处理反馈",
                    fb.title or "待处理",
                    fmt_dt(fb.updated_at or fb.created_at),
                )
            )
    elif user.role == "sales":
        for inq in (
            db.query(Inquiry)
            .filter(Inquiry.creator_id == user.id, Inquiry.status == "quoted")
            .order_by(Inquiry.updated_at.desc(), Inquiry.id.desc())
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
            .options(joinedload(Inquiry.order))
            .filter(Inquiry.creator_id == user.id, Inquiry.status == "selling")
            .order_by(Inquiry.updated_at.desc(), Inquiry.id.desc())
            .all()
        ):
            if inq.order:
                continue
            rejected = bool((inq.audit_reject_remark or "").strip() or (inq.audit_reject_order_no or "").strip())
            reason = (inq.audit_reject_remark or "").strip()
            items.append(
                _todo(
                    "reject" if rejected else "quoted",
                    f"{'处理被驳回订单' if rejected else '提交审核'} {inq.audit_reject_order_no or inq.no}",
                    f"#/inquiries/{inq.id}",
                    "已驳回" if rejected else "销售中",
                    (f"原因：{reason}" if rejected and reason else "") or inq.customer_name or "提交管理员审核或结束询价",
                    fmt_dt(inq.updated_at or inq.created_at),
                )
            )
        q = filter_orders(db.query(Order).options(joinedload(Order.inquiry)), user)
        for o in (
            q.filter(Order.status == "draft")
            .order_by(Order.updated_at.desc(), Order.id.desc())
            .all()
        ):
            customer = (o.customer_name or "") or (o.inquiry.customer_name if o.inquiry else "")
            items.append(
                _todo(
                    "fill",
                    f"完善并提交销售订单 {o.no}",
                    f"#/orders/{o.id}",
                    "草稿",
                    customer or "待填写后提交审核",
                    fmt_dt(o.updated_at or o.created_at),
                )
            )
        for o in (
            q.filter(Order.status == "contract")
            .order_by(Order.updated_at.desc(), Order.id.desc())
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
            .outerjoin(Order, Order.inquiry_id == Inquiry.id)
            .filter(
                Inquiry.status.in_(("pending_quote", "quoted", "selling")),
                Order.id.is_(None),
            )
            .order_by(Inquiry.updated_at.desc(), Inquiry.id.desc())
            .all()
        ):
            waiting = inq.status == "pending_quote"
            items.append(
                _todo(
                    "quote",
                    f"{'询价待报价' if waiting else '询价可报价'} {inq.no}",
                    f"#/inquiries/{inq.id}",
                    "待报价" if waiting else "可报价",
                    inq.customer_name or ("待报价" if waiting else "可继续提交报价"),
                    fmt_dt(inq.updated_at or inq.created_at),
                )
            )
        pos = filter_purchase_orders(db.query(PurchaseOrder), user)
        for po in (
            pos.filter(PurchaseOrder.status.in_(("pending_fill", "rejected")))
            .order_by(PurchaseOrder.updated_at.desc(), PurchaseOrder.id.desc())
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
        for po in (
            pos.filter(PurchaseOrder.status.in_(PO_ADVANCE_STATUSES))
            .order_by(PurchaseOrder.updated_at.desc(), PurchaseOrder.id.desc())
            .all()
        ):
            items.append(
                _todo(
                    "fill",
                    f"推进采购单 {po.no}",
                    f"#/purchase-orders/{po.id}",
                    PO_ADVANCE_TAG.get(po.status, "进行中"),
                    po.supplier_name or "待更新物流或确认节点",
                    fmt_dt(po.updated_at or po.created_at),
                )
            )
    elif user.role == "finance":
        po_skip = ("pending_fill", "pending_audit", "rejected")
        q = (
            db.query(FinanceVoucher)
            .options(joinedload(FinanceVoucher.allocs).joinedload(FinanceAllocLine.purchase_order))
            .outerjoin(FinanceAllocLine, FinanceAllocLine.voucher_id == FinanceVoucher.id)
            .outerjoin(PurchaseOrder, FinanceAllocLine.purchase_order_id == PurchaseOrder.id)
            .filter(
                FinanceVoucher.status == "pending",
                or_(
                    FinanceVoucher.direction != "payment",
                    PurchaseOrder.id.is_(None),
                    ~PurchaseOrder.status.in_(po_skip),
                ),
            )
            .order_by(FinanceVoucher.created_at.desc(), FinanceVoucher.id.desc())
        )
        seen = set()
        for v in q.all():
            if v.id in seen:
                continue
            seen.add(v.id)
            po_no = next((a.purchase_order.no for a in (v.allocs or []) if a.purchase_order), "")
            is_pay = v.direction == "payment"
            items.append(
                _todo(
                    "fill",
                    f"{'填写付款单' if is_pay else '填写收款单'} {v.no}",
                    f"#/finance/{'payments' if is_pay else 'receipts'}/{v.id}",
                    "待填写",
                    (f"关联 {po_no}" if po_no else "") or v.partner_name or v.summary or ("请登记付款" if is_pay else "请登记收款"),
                    fmt_dt(v.created_at),
                )
            )
    items.sort(key=lambda x: x.get("time") or "", reverse=True)
    return items


@router.get("")
def dashboard(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    cards = []
    if user.role == "admin":
        cards.append(
            {
                "key": "pending_quote",
                "label": "待审核询价单",
                "count": db.query(Inquiry).filter(Inquiry.status == "pending_quote").count(),
            }
        )
        cards.append(
            {
                "key": "pending_audit",
                "label": "待审核销售单",
                "count": db.query(Order).filter(Order.status == "pending_audit").count(),
            }
        )
        pos = filter_purchase_orders(db.query(PurchaseOrder), user)
        cards.append(
            {
                "key": "po_pending",
                "label": "待审核采购单",
                "count": pos.filter(PurchaseOrder.status == "pending_audit").count(),
            }
        )
    else:
        inq = filter_inquiries(db.query(Inquiry), user)
        orders = filter_orders(db.query(Order), user)
        if user.role in ("sales", "purchase"):
            q = inq
            cards.append({"key": "pending_quote", "label": "待报价询价", "count": q.filter(Inquiry.status == "pending_quote").count()})
            cards.append({"key": "quoted", "label": "已报价询价", "count": q.filter(Inquiry.status == "quoted").count()})
        if user.role == "sales":
            cards.append({"key": "selling", "label": "销售中", "count": inq.filter(Inquiry.status == "selling").count()})
            cards.append({"key": "done", "label": "已完成", "count": inq.filter(Inquiry.status.in_(("won", "closed"))).count()})
            cards.append({"key": "contract", "label": "待填合同", "count": orders.filter(Order.status == "contract").count()})
            cards.append({"key": "fulfilling", "label": "履约中", "count": orders.filter(Order.status == "fulfilling").count()})
        if user.role == "finance":
            pending_recv = (
                db.query(FinanceVoucher)
                .filter(FinanceVoucher.direction == "receipt", FinanceVoucher.status == "pending")
                .count()
            )
            pending_pay = (
                db.query(FinanceVoucher)
                .filter(FinanceVoucher.direction == "payment", FinanceVoucher.status == "pending")
                .count()
            )
            cards.append({"key": "rec_fill", "label": "待填收款单", "count": pending_recv})
            cards.append({"key": "pay_fill", "label": "待填付款单", "count": pending_pay})
        if user.role == "purchase":
            pos = filter_purchase_orders(db.query(PurchaseOrder), user)
            cards.append({"key": "po_fill", "label": "待填采购单", "count": pos.filter(PurchaseOrder.status == "pending_fill").count()})
            cards.append({"key": "po_pending", "label": "待审采购单", "count": pos.filter(PurchaseOrder.status == "pending_audit").count()})
            cards.append({"key": "po_progress", "label": "采购进行中", "count": pos.filter(PurchaseOrder.status.in_(("in_progress", "stuffed", "domestic_inbound", "domestic_accepted", "overseas_transit", "inbound", "accepted"))).count()})
    todos = build_todos(db, user)
    return {
        "name": user.name,
        "role": user.role,
        "cards": cards,
        "todos": todos,
        "todo_count": len(todos),
    }
