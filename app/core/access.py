from typing import Optional

from sqlalchemy import or_

from app.db.models import Inquiry, Order, PurchaseOrder, Quote, User


def is_sales_owner(user: User, order: Order) -> bool:
    if not user or not order:
        return False
    if order.creator_id == user.id or getattr(order, "salesperson_id", None) == user.id:
        return True
    if order.inquiry and order.inquiry.creator_id == user.id:
        return True
    return False


def is_purchase_owner(user: User, po: PurchaseOrder) -> bool:
    if not user or not po or user.role != "purchase":
        return False
    return po.purchaser_id == user.id


def infer_po_purchaser_id(order: Optional[Order]) -> Optional[int]:
    """销售单采用哪份报价，采购单就归该报价的采购员。"""
    if not order:
        return None
    quote = getattr(order, "quote", None)
    if quote is not None and getattr(quote, "purchaser_id", None):
        return quote.purchaser_id
    inq = getattr(order, "inquiry", None)
    if not inq:
        return None
    selected = getattr(inq, "selected_quote", None)
    if selected is not None and getattr(selected, "purchaser_id", None):
        return selected.purchaser_id
    selected_id = getattr(inq, "selected_quote_id", None)
    if not selected_id:
        return None
    for q in list(getattr(inq, "quotes", None) or []):
        if q.id == selected_id and getattr(q, "purchaser_id", None):
            return q.purchaser_id
    return None


def can_view_inquiry(user: User, inq: Inquiry) -> bool:
    if not user or not inq:
        return False
    if user.role in ("admin", "purchase"):
        return True
    if user.role == "sales":
        return inq.creator_id == user.id
    if user.role == "finance":
        return inq.order is not None
    return False


def can_view_order(user: User, order: Order) -> bool:
    if not user or not order:
        return False
    if user.role == "admin":
        return True
    if user.role == "finance":
        return True
    if user.role == "sales":
        return is_sales_owner(user, order)
    if user.role == "purchase":
        if order.status in ("draft", "pending_audit", "rejected"):
            return False
        return infer_po_purchaser_id(order) == user.id
    return False


def can_view_po(user: User, po: PurchaseOrder) -> bool:
    if not user or not po:
        return False
    if user.role == "admin":
        return True
    if user.role == "finance":
        return True
    if user.role == "purchase":
        return is_purchase_owner(user, po)
    if user.role == "sales":
        return is_sales_owner(user, po.sales_order) if po.sales_order else False
    return False


def filter_inquiries(q, user: User):
    if user.role in ("admin", "purchase"):
        return q
    if user.role == "sales":
        return q.filter(Inquiry.creator_id == user.id)
    if user.role == "finance":
        return q.join(Order, Order.inquiry_id == Inquiry.id)
    return q.filter(Inquiry.id == 0)


def filter_orders(q, user: User):
    if user.role == "admin" or user.role == "finance":
        return q
    if user.role == "sales":
        return q.outerjoin(Inquiry, Order.inquiry_id == Inquiry.id).filter(
            or_(
                Order.creator_id == user.id,
                Order.salesperson_id == user.id,
                Inquiry.creator_id == user.id,
            )
        )
    if user.role == "purchase":
        return q.join(Quote, Order.quote_id == Quote.id).filter(
            Quote.purchaser_id == user.id,
            Order.status.notin_(("draft", "pending_audit", "rejected")),
        )
    return q.filter(Order.id == 0)


def filter_purchase_orders(q, user: User):
    if user.role in ("admin", "finance"):
        return q
    if user.role == "purchase":
        return q.filter(PurchaseOrder.purchaser_id == user.id)
    if user.role == "sales":
        return (
            q.outerjoin(Order, PurchaseOrder.sales_order_id == Order.id)
            .outerjoin(Inquiry, Order.inquiry_id == Inquiry.id)
            .filter(
                or_(
                    Order.creator_id == user.id,
                    Order.salesperson_id == user.id,
                    Inquiry.creator_id == user.id,
                )
            )
        )
    return q.filter(PurchaseOrder.id == 0)
