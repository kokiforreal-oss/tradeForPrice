from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.core.e2e import EncryptedMoney, EncryptedName


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_categories.id"), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    spec: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(32), default="pcs")
    primary_unit: Mapped[str] = mapped_column(String(32), default="")
    aux_unit: Mapped[str] = mapped_column(String(32), default="")
    sales_unit: Mapped[str] = mapped_column(String(32), default="")
    product_type: Mapped[str] = mapped_column(String(32), default="实物")
    pricing_method: Mapped[str] = mapped_column(String(32), default="固定价")
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_categories.id"), nullable=True)
    cost_price: Mapped[Optional[str]] = mapped_column(EncryptedMoney(), nullable=True)
    remark: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    category: Mapped[Optional["ProductCategory"]] = relationship()


class Inquiry(Base):
    __tablename__ = "inquiries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(EncryptedName())
    contact_name: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    currency: Mapped[str] = mapped_column(String(8), default="RMB")
    requirement: Mapped[str] = mapped_column(Text, default="")
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending_quote", index=True)
    close_reason: Mapped[str] = mapped_column(Text, default="")
    quote_round: Mapped[int] = mapped_column(Integer, default=1)
    requote_reason: Mapped[str] = mapped_column(Text, default="")
    requote_log: Mapped[str] = mapped_column(Text, default="[]")
    audit_reject_remark: Mapped[str] = mapped_column(Text, default="")
    audit_reject_order_no: Mapped[str] = mapped_column(String(32), default="")
    selected_quote_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("quotes.id", use_alter=True, name="fk_inquiry_selected_quote"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    creator: Mapped["User"] = relationship(foreign_keys=[creator_id])
    lines: Mapped[List["InquiryLine"]] = relationship(back_populates="inquiry", cascade="all, delete-orphan")
    quotes: Mapped[List["Quote"]] = relationship(
        back_populates="inquiry", foreign_keys="Quote.inquiry_id", cascade="all, delete-orphan"
    )
    selected_quote: Mapped[Optional["Quote"]] = relationship(foreign_keys=[selected_quote_id], post_update=True)
    order: Mapped[Optional["Order"]] = relationship(back_populates="inquiry", uselist=False)


class InquiryLine(Base):
    __tablename__ = "inquiry_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    spec: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(32), default="pcs")
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    target_price: Mapped[Optional[str]] = mapped_column(EncryptedMoney(), nullable=True)
    remark: Mapped[str] = mapped_column(String(200), default="")

    inquiry: Mapped["Inquiry"] = relationship(back_populates="lines")
    product: Mapped[Optional["Product"]] = relationship()


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    purchaser_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text, default="")
    lead_days: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    inquiry: Mapped["Inquiry"] = relationship(back_populates="quotes", foreign_keys=[inquiry_id])
    purchaser: Mapped["User"] = relationship(foreign_keys=[purchaser_id])
    lines: Mapped[List["QuoteLine"]] = relationship(back_populates="quote", cascade="all, delete-orphan")


class QuoteLine(Base):
    __tablename__ = "quote_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"), index=True)
    inquiry_line_id: Mapped[int] = mapped_column(ForeignKey("inquiry_lines.id"))
    unit_price: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)

    quote: Mapped["Quote"] = relationship(back_populates="lines")
    inquiry_line: Mapped["InquiryLine"] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    inquiry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inquiries.id"), unique=True, nullable=True)
    quote_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    creator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    customer_name: Mapped[str] = mapped_column(EncryptedName(), default="")
    customer_country: Mapped[str] = mapped_column(String(80), default="")
    currency: Mapped[str] = mapped_column(String(8), default="RMB")
    status: Mapped[str] = mapped_column(String(20), default="pending_audit", index=True)
    contract_no: Mapped[str] = mapped_column(String(64), default="")
    contract_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    contract_remark: Mapped[str] = mapped_column(Text, default="")
    contract_file: Mapped[str] = mapped_column(String(255), default="")
    incoterm: Mapped[str] = mapped_column(String(16), default="")
    loading_port: Mapped[str] = mapped_column(String(120), default="")
    destination_port: Mapped[str] = mapped_column(String(120), default="")
    payment_terms: Mapped[str] = mapped_column(String(200), default="")
    factory_address: Mapped[str] = mapped_column(String(200), default="")
    audit_remark: Mapped[str] = mapped_column(Text, default="")
    first_payment_amount: Mapped[Optional[str]] = mapped_column(EncryptedMoney(), nullable=True)
    payment_remark: Mapped[str] = mapped_column(Text, default="")
    production_remark: Mapped[str] = mapped_column(Text, default="")
    logistics_company: Mapped[str] = mapped_column(String(100), default="")
    tracking_no: Mapped[str] = mapped_column(String(100), default="")
    shipping_remark: Mapped[str] = mapped_column(Text, default="")
    balance_amount: Mapped[Optional[str]] = mapped_column(EncryptedMoney(), nullable=True)
    balance_remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    voucher_type: Mapped[str] = mapped_column(String(20), default="sale")
    doc_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    project: Mapped[str] = mapped_column(String(120), default="")
    salesperson_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    header_tax_rate: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    order_remark: Mapped[str] = mapped_column(String(200), default="")
    freight: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    extra_tax: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    deposit: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    settle_method: Mapped[str] = mapped_column(String(40), default="")
    pay_account: Mapped[str] = mapped_column(String(80), default="")
    pay_deposit: Mapped[bool] = mapped_column(default=False)
    total: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)

    inquiry: Mapped[Optional["Inquiry"]] = relationship(back_populates="order")
    quote: Mapped[Optional["Quote"]] = relationship()
    creator: Mapped[Optional["User"]] = relationship(foreign_keys=[creator_id])
    salesperson: Mapped[Optional["User"]] = relationship(foreign_keys=[salesperson_id])
    lines: Mapped[List["OrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    logs: Mapped[List["OrderLog"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    purchase_orders: Mapped[List["PurchaseOrder"]] = relationship(back_populates="sales_order")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(64), default="")
    barcode: Mapped[str] = mapped_column(String(64), default="")
    product_name: Mapped[str] = mapped_column(String(200), default="")
    spec: Mapped[str] = mapped_column(String(200), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    line_remark: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(32), default="pcs")
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    tax_rate: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    supplier_name: Mapped[str] = mapped_column(EncryptedName(), default="")
    is_gift: Mapped[bool] = mapped_column(default=False)

    order: Mapped["Order"] = relationship(back_populates="lines")
    product: Mapped[Optional["Product"]] = relationship()


class OrderLog(Base):
    __tablename__ = "order_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20))
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    order: Mapped["Order"] = relationship(back_populates="logs")
    operator: Mapped["User"] = relationship()


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    supplier_name: Mapped[str] = mapped_column(EncryptedName(), default="")
    contact_name: Mapped[str] = mapped_column(String(64), default="")
    contact_phone: Mapped[str] = mapped_column(String(64), default="")
    payment_terms: Mapped[str] = mapped_column(String(200), default="")
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="RMB")
    total: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    remark: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending_audit", index=True)
    audit_remark: Mapped[str] = mapped_column(Text, default="")
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    doc_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    purchaser_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    project: Mapped[str] = mapped_column(String(120), default="")
    freight: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    extra_tax: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    deposit: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    settle_method: Mapped[str] = mapped_column(String(40), default="")
    pay_account: Mapped[str] = mapped_column(String(80), default="")
    pay_deposit: Mapped[bool] = mapped_column(default=False)
    supplier_bank: Mapped[str] = mapped_column(EncryptedName(), default="")
    supplier_account: Mapped[str] = mapped_column(EncryptedName(), default="")
    shipping_warehouse: Mapped[str] = mapped_column(String(80), default="")

    sales_order: Mapped["Order"] = relationship(back_populates="purchase_orders")
    creator: Mapped["User"] = relationship(foreign_keys=[creator_id])
    purchaser: Mapped[Optional["User"]] = relationship(foreign_keys=[purchaser_id])
    lines: Mapped[List["PurchaseOrderLine"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")
    logs: Mapped[List["PurchaseOrderLog"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(64), default="")
    product_name: Mapped[str] = mapped_column(String(200), default="")
    spec: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(32), default="pcs")
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    barcode: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    line_remark: Mapped[str] = mapped_column(String(200), default="")
    tax_rate: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    warehouse: Mapped[str] = mapped_column(String(80), default="")

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")
    product: Mapped[Optional["Product"]] = relationship()


class PurchaseOrderLog(Base):
    __tablename__ = "purchase_order_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="status")
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20), default="")
    logistics_company: Mapped[str] = mapped_column(String(100), default="")
    tracking_no: Mapped[str] = mapped_column(String(100), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="logs")
    operator: Mapped["User"] = relationship()


class FinanceReceipt(Base):
    __tablename__ = "finance_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    biz_date: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(40), default="银行转账")
    remark: Mapped[str] = mapped_column(String(200), default="")
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    order: Mapped["Order"] = relationship()
    operator: Mapped["User"] = relationship()


class FinancePayment(Base):
    __tablename__ = "finance_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    biz_date: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(40), default="银行转账")
    remark: Mapped[str] = mapped_column(String(200), default="")
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    purchase_order: Mapped["PurchaseOrder"] = relationship()
    operator: Mapped["User"] = relationship()


class FinanceInvoice(Base):
    __tablename__ = "finance_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True)
    purchase_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    invoice_no: Mapped[str] = mapped_column(String(64))
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    tax_amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    total: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    biz_date: Mapped[date] = mapped_column(Date)
    remark: Mapped[str] = mapped_column(String(200), default="")
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    order: Mapped[Optional["Order"]] = relationship()
    purchase_order: Mapped[Optional["PurchaseOrder"]] = relationship()
    operator: Mapped["User"] = relationship()
    writeoffs: Mapped[List["FinanceWriteoff"]] = relationship(back_populates="invoice")


class FinanceWriteoff(Base):
    __tablename__ = "finance_writeoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("finance_invoices.id"), index=True)
    receipt_id: Mapped[Optional[int]] = mapped_column(ForeignKey("finance_receipts.id"), nullable=True)
    payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("finance_payments.id"), nullable=True)
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    biz_date: Mapped[date] = mapped_column(Date)
    remark: Mapped[str] = mapped_column(String(200), default="")
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    invoice: Mapped["FinanceInvoice"] = relationship(back_populates="writeoffs")
    operator: Mapped["User"] = relationship()


class FinanceVoucher(Base):
    __tablename__ = "finance_vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(20), index=True)
    voucher_type: Mapped[str] = mapped_column(String(20), default="collect")
    biz_date: Mapped[date] = mapped_column(Date)
    partner_name: Mapped[str] = mapped_column(EncryptedName(), default="")
    biz_type: Mapped[str] = mapped_column(String(40), default="")
    salesperson_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    summary: Mapped[str] = mapped_column(String(200), default="")
    remark: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="posted", index=True)
    cash_discount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    salesperson: Mapped[Optional["User"]] = relationship(foreign_keys=[salesperson_id])
    operator: Mapped["User"] = relationship(foreign_keys=[operator_id])
    settles: Mapped[List["FinanceSettleLine"]] = relationship(
        back_populates="voucher", cascade="all, delete-orphan"
    )
    allocs: Mapped[List["FinanceAllocLine"]] = relationship(
        back_populates="voucher", cascade="all, delete-orphan"
    )


class FinanceSettleLine(Base):
    __tablename__ = "finance_settle_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voucher_id: Mapped[int] = mapped_column(ForeignKey("finance_vouchers.id"), index=True)
    sort_no: Mapped[int] = mapped_column(Integer, default=1)
    method: Mapped[str] = mapped_column(String(40), default="银行转账")
    account: Mapped[str] = mapped_column(String(80), default="")
    amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RMB")
    remark: Mapped[str] = mapped_column(String(200), default="")

    voucher: Mapped["FinanceVoucher"] = relationship(back_populates="settles")


class FinanceAllocLine(Base):
    __tablename__ = "finance_alloc_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voucher_id: Mapped[int] = mapped_column(ForeignKey("finance_vouchers.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(20), default="sales_order")
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    purchase_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=True, index=True
    )
    this_amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)
    discount_amount: Mapped[str] = mapped_column(EncryptedMoney(allow_none=False), default=0)

    voucher: Mapped["FinanceVoucher"] = relationship(back_populates="allocs")
    order: Mapped[Optional["Order"]] = relationship()
    purchase_order: Mapped[Optional["PurchaseOrder"]] = relationship()

