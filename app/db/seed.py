from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.db.models import Product, User


def seed(db: Session) -> None:
    """仅在用户表为空时写入演示账号；已有账号与业务数据一律不改、不删。"""
    if db.query(User).first():
        return
    users = [
        ("admin", "admin123", "系统管理员", "admin"),
        ("sales", "sales123", "张销售", "sales"),
        ("purchase", "purchase123", "李采购", "purchase"),
        ("finance", "finance123", "王财务", "finance"),
    ]
    for username, password, name, role in users:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                name=name,
                role=role,
            )
        )
    db.commit()


def ensure_catalog(db: Session) -> None:
    changed = False
    for p in db.query(Product).all():
        if not (p.primary_unit or "").strip():
            p.primary_unit = p.unit or "pcs"
            changed = True
        if not (p.sales_unit or "").strip():
            p.sales_unit = p.unit or "pcs"
            changed = True
        if not (p.product_type or "").strip():
            p.product_type = "实物"
            changed = True
        if not (p.pricing_method or "").strip():
            p.pricing_method = "固定价"
            changed = True
    if changed:
        db.commit()
