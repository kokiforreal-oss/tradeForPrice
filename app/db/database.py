import logging
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.sql.sqltypes import NullType

from app.config import settings

log = logging.getLogger("trade.db")


def _database_url(url: str) -> str:
    if url.startswith("mysql://"):
        return "mysql+pymysql://" + url[len("mysql://") :]
    return url


database_url = _database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine_kwargs: dict = {
    "connect_args": connect_args,
    "pool_pre_ping": True,
}
if database_url.startswith("mysql"):
    engine_kwargs["pool_recycle"] = 3600

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ident(name: str) -> str:
    cleaned = name.replace("`", "").replace('"', "")
    if engine.dialect.name == "mysql":
        return f"`{cleaned}`"
    return f'"{cleaned}"'


def _is_destructive_sql(sql: str) -> bool:
    joined = " ".join(sql.lower().split())
    return any(
        token in joined
        for token in ("drop table", "drop database", "drop schema", "truncate table", "truncate ")
    )


def _column_default_sql(col) -> Optional[str]:
    impl = getattr(col.type, "impl", col.type)
    if impl is None:
        impl = col.type
    if isinstance(impl, Boolean):
        return "0"
    if isinstance(impl, (Integer, Numeric)):
        return "0"
    if isinstance(impl, (String, Text)):
        return "''"
    if isinstance(impl, (Date, DateTime, NullType)):
        return None
    return "''"


def _missing_column_statements(insp) -> list:
    """按当前模型给旧表补列；已有列和行一律不动。"""
    tables = set(insp.get_table_names())
    out = []
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            type_sql = col.type.compile(dialect=engine.dialect)
            tbl, cname = _ident(table.name), _ident(col.name)
            if col.nullable:
                out.append(f"ALTER TABLE {tbl} ADD COLUMN {cname} {type_sql} NULL")
                continue
            default = _column_default_sql(col)
            if default is None:
                out.append(f"ALTER TABLE {tbl} ADD COLUMN {cname} {type_sql} NULL")
            else:
                out.append(f"ALTER TABLE {tbl} ADD COLUMN {cname} {type_sql} NOT NULL DEFAULT {default}")
    return out


def _relax_not_null_statements(insp) -> list:
    if engine.dialect.name != "mysql":
        return []
    tables = set(insp.get_table_names())
    adds = []
    if "orders" in tables:
        ocols = {c["name"]: c for c in insp.get_columns("orders")}
        if "inquiry_id" in ocols and not ocols["inquiry_id"].get("nullable", True):
            adds.append("ALTER TABLE orders MODIFY COLUMN inquiry_id INTEGER NULL")
        if "quote_id" in ocols and not ocols["quote_id"].get("nullable", True):
            adds.append("ALTER TABLE orders MODIFY COLUMN quote_id INTEGER NULL")
    if "inquiry_lines" in tables:
        lcols = {c["name"]: c for c in insp.get_columns("inquiry_lines")}
        if "product_id" in lcols and not lcols["product_id"].get("nullable", True):
            adds.append("ALTER TABLE inquiry_lines MODIFY COLUMN product_id INTEGER NULL")
    if "purchase_orders" in tables:
        pcols = {c["name"]: c for c in insp.get_columns("purchase_orders")}
        if "sales_order_id" in pcols and not pcols["sales_order_id"].get("nullable", True):
            adds.append("ALTER TABLE purchase_orders MODIFY COLUMN sales_order_id INTEGER NULL")
    return adds


def has_business_data() -> bool:
    insp = inspect(engine)
    names = set(insp.get_table_names())
    markers = (
        "users",
        "products",
        "inquiries",
        "quotes",
        "orders",
        "purchase_orders",
        "finance_vouchers",
        "finance_receipts",
        "finance_payments",
    )
    with engine.connect() as conn:
        for table in markers:
            if table not in names:
                continue
            n = conn.execute(text(f"SELECT COUNT(*) FROM {_ident(table)}")).scalar() or 0
            if int(n) > 0:
                return True
    return False


def preserve_org_key() -> None:
    """已有业务数据时禁止生成新的加密密钥，否则历史密文会全部读不出来。"""
    from app.core.e2e import KEY_PATH, load_org_key

    if KEY_PATH.exists():
        load_org_key()
        return
    if has_business_data():
        raise RuntimeError(
            "检测到已有业务数据，但缺少 data/e2e.key。"
            "拒绝自动生成新密钥，否则历史加密字段将无法解密。"
            "请从备份恢复 data/e2e.key 后再启动。"
        )
    load_org_key()


def ensure_schema() -> None:
    """增量升级：只建缺失表/列，从不删表、清库或覆盖已有行。"""
    import app.db.models  # noqa: F401

    insp = inspect(engine)
    adds = []
    adds.extend(_missing_column_statements(insp))
    adds.extend(_relax_not_null_statements(insp))
    adds.extend(_e2e_alter_statements(insp))
    for stmt in adds:
        if _is_destructive_sql(stmt):
            raise RuntimeError(f"拒绝执行破坏性 SQL：{stmt}")
        log.info("schema patch: %s", stmt)
        with engine.begin() as conn:
            conn.execute(text(stmt))
    _backfill_pending_payment_vouchers()
    _backfill_po_purchasers()
    _encrypt_legacy_plaintexts()


def _backfill_pending_payment_vouchers() -> None:
    insp = inspect(engine)
    if "finance_vouchers" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("finance_vouchers")}
    if "status" not in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE finance_vouchers SET status='pending' "
                "WHERE direction='payment' AND (status IS NULL OR status='') "
                "AND summary LIKE '%待登记付款%'"
            )
        )
        conn.execute(
            text("UPDATE finance_vouchers SET status='posted' WHERE status IS NULL OR status=''")
        )


def _backfill_po_purchasers() -> None:
    from sqlalchemy.orm import joinedload

    from app.core.access import infer_po_purchaser_id
    from app.db.models import Inquiry, Order, PurchaseOrder

    insp = inspect(engine)
    if "purchase_orders" not in set(insp.get_table_names()):
        return
    db = SessionLocal()
    try:
        pos = (
            db.query(PurchaseOrder)
            .options(
                joinedload(PurchaseOrder.creator),
                joinedload(PurchaseOrder.sales_order).joinedload(Order.quote),
                joinedload(PurchaseOrder.sales_order).joinedload(Order.inquiry).joinedload(Inquiry.quotes),
                joinedload(PurchaseOrder.sales_order).joinedload(Order.inquiry).joinedload(Inquiry.selected_quote),
            )
            .all()
        )
        changed = False
        for po in pos:
            pid = None
            if po.sales_order:
                pid = infer_po_purchaser_id(po.sales_order)
            elif not po.purchaser_id and po.creator and po.creator.role == "purchase":
                pid = po.creator_id
            if pid and po.purchaser_id != pid:
                po.purchaser_id = pid
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def _sqltype(col) -> str:
    return str(col.get("type", "")).upper()


def _e2e_alter_statements(insp) -> list[str]:
    if engine.dialect.name != "mysql":
        return []
    money_nn = [
        ("quotes", "total"),
        ("quote_lines", "unit_price"),
        ("quote_lines", "amount"),
        ("orders", "freight"),
        ("orders", "extra_tax"),
        ("orders", "deposit"),
        ("orders", "total"),
        ("order_lines", "unit_price"),
        ("order_lines", "amount"),
        ("purchase_orders", "total"),
        ("purchase_orders", "freight"),
        ("purchase_orders", "extra_tax"),
        ("purchase_orders", "deposit"),
        ("purchase_order_lines", "unit_price"),
        ("purchase_order_lines", "amount"),
        ("finance_receipts", "amount"),
        ("finance_payments", "amount"),
        ("finance_invoices", "amount"),
        ("finance_invoices", "tax_amount"),
        ("finance_invoices", "total"),
        ("finance_writeoffs", "amount"),
        ("finance_vouchers", "cash_discount"),
        ("finance_settle_lines", "amount"),
        ("finance_alloc_lines", "this_amount"),
        ("finance_alloc_lines", "discount_amount"),
    ]
    money_null = [
        ("products", "cost_price"),
        ("inquiry_lines", "target_price"),
        ("orders", "first_payment_amount"),
        ("orders", "balance_amount"),
    ]
    names = [
        ("inquiries", "customer_name"),
        ("orders", "customer_name"),
        ("order_lines", "supplier_name"),
        ("purchase_orders", "supplier_name"),
        ("purchase_orders", "supplier_bank"),
        ("purchase_orders", "supplier_account"),
        ("finance_vouchers", "partner_name"),
    ]
    tables = set(insp.get_table_names())
    out: list[str] = []
    for table, col in money_nn:
        if table not in tables:
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        if col not in cols:
            continue
        if "VARCHAR" in _sqltype(cols[col]) and "512" in _sqltype(cols[col]):
            continue
        out.append(f"ALTER TABLE {table} MODIFY COLUMN {col} VARCHAR(512) NOT NULL DEFAULT ''")
    for table, col in money_null:
        if table not in tables:
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        if col not in cols:
            continue
        if "VARCHAR" in _sqltype(cols[col]) and "512" in _sqltype(cols[col]):
            continue
        out.append(f"ALTER TABLE {table} MODIFY COLUMN {col} VARCHAR(512) NULL")
    for table, col in names:
        if table not in tables:
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        if col not in cols:
            continue
        if "VARCHAR" in _sqltype(cols[col]) and "512" in _sqltype(cols[col]):
            continue
        out.append(f"ALTER TABLE {table} MODIFY COLUMN {col} VARCHAR(512) NOT NULL DEFAULT ''")
    return out


def _encrypt_legacy_plaintexts() -> None:
    from app.core.e2e import is_enc, store_money, store_name
    from app.db.models import (
        FinanceAllocLine,
        FinanceInvoice,
        FinancePayment,
        FinanceReceipt,
        FinanceSettleLine,
        FinanceVoucher,
        FinanceWriteoff,
        Inquiry,
        InquiryLine,
        Order,
        OrderLine,
        Product,
        PurchaseOrder,
        PurchaseOrderLine,
        Quote,
        QuoteLine,
    )

    db = SessionLocal()
    try:
        changed = False

        def enc_money_attr(row, attr, allow_none=False):
            nonlocal changed
            val = getattr(row, attr)
            if val is None or val == "":
                if allow_none:
                    return
                setattr(row, attr, 0)
                changed = True
                return
            if is_enc(val):
                return
            setattr(row, attr, store_money(val))
            changed = True

        def enc_name_attr(row, attr):
            nonlocal changed
            val = getattr(row, attr)
            if not val or is_enc(val):
                return
            setattr(row, attr, store_name(val))
            changed = True

        for p in db.query(Product).all():
            enc_money_attr(p, "cost_price", allow_none=True)
        for r in db.query(Inquiry).all():
            enc_name_attr(r, "customer_name")
        for r in db.query(InquiryLine).all():
            enc_money_attr(r, "target_price", allow_none=True)
        for r in db.query(Quote).all():
            enc_money_attr(r, "total")
        for r in db.query(QuoteLine).all():
            enc_money_attr(r, "unit_price")
            enc_money_attr(r, "amount")
        for r in db.query(Order).all():
            enc_name_attr(r, "customer_name")
            for attr in ("first_payment_amount", "balance_amount"):
                enc_money_attr(r, attr, allow_none=True)
            for attr in ("freight", "extra_tax", "deposit", "total"):
                enc_money_attr(r, attr)
        for r in db.query(OrderLine).all():
            enc_name_attr(r, "supplier_name")
            enc_money_attr(r, "unit_price")
            enc_money_attr(r, "amount")
        for r in db.query(PurchaseOrder).all():
            enc_name_attr(r, "supplier_name")
            enc_name_attr(r, "supplier_bank")
            enc_name_attr(r, "supplier_account")
            for attr in ("total", "freight", "extra_tax", "deposit"):
                enc_money_attr(r, attr)
        for r in db.query(PurchaseOrderLine).all():
            enc_money_attr(r, "unit_price")
            enc_money_attr(r, "amount")
        for r in db.query(FinanceReceipt).all():
            enc_money_attr(r, "amount")
        for r in db.query(FinancePayment).all():
            enc_money_attr(r, "amount")
        for r in db.query(FinanceInvoice).all():
            for attr in ("amount", "tax_amount", "total"):
                enc_money_attr(r, attr)
        for r in db.query(FinanceWriteoff).all():
            enc_money_attr(r, "amount")
        for r in db.query(FinanceVoucher).all():
            enc_name_attr(r, "partner_name")
            enc_money_attr(r, "cash_discount")
        for r in db.query(FinanceSettleLine).all():
            enc_money_attr(r, "amount")
        for r in db.query(FinanceAllocLine).all():
            enc_money_attr(r, "this_amount")
            enc_money_attr(r, "discount_amount")
        if changed:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
