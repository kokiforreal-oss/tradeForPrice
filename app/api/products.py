from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.core.auth import get_current_user, require_roles
from app.db.database import get_db
from app.core.e2e import MoneyIn
from app.db.models import InquiryLine, Product, ProductCategory, User
from app.core.utils import fmt_dt, to_float

router = APIRouter(prefix="/api/products", tags=["products"])


class CategoryIn(BaseModel):
    code: str
    name: str
    parent_id: Optional[int] = None
    sort: int = 0


class ProductIn(BaseModel):
    sku: str
    name: str
    spec: str = ""
    unit: str = "pcs"
    primary_unit: str = ""
    aux_unit: str = ""
    sales_unit: str = ""
    product_type: str = "实物"
    pricing_method: str = "固定价"
    category_id: Optional[int] = None
    cost_price: Optional[MoneyIn] = None
    remark: str = ""
    status: str = "active"


def product_out(p: Product, show_cost: bool) -> dict:
    cat = p.category
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "spec": p.spec,
        "unit": p.unit,
        "primary_unit": p.primary_unit or p.unit,
        "aux_unit": p.aux_unit or "",
        "sales_unit": p.sales_unit or p.unit,
        "product_type": p.product_type or "实物",
        "pricing_method": p.pricing_method or "固定价",
        "category_id": p.category_id,
        "category_code": cat.code if cat else "",
        "category_name": cat.name if cat else "",
        "cost_price": to_float(p.cost_price) if show_cost else None,
        "remark": p.remark,
        "status": p.status,
        "created_at": fmt_dt(p.created_at),
    }


def category_out(c: ProductCategory, children: list) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "parent_id": c.parent_id,
        "sort": c.sort,
        "children": children,
    }


def build_tree(rows: List[ProductCategory]) -> list:
    by_parent: dict = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)
    for lst in by_parent.values():
        lst.sort(key=lambda x: (x.sort, x.code))

    def walk(parent_id):
        return [category_out(c, walk(c.id)) for c in by_parent.get(parent_id, [])]

    return walk(None)


def descendant_ids(rows: List[ProductCategory], cat_id: int) -> List[int]:
    by_parent: dict = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)
    out: List[int] = []

    def walk(cid: int):
        out.append(cid)
        for ch in by_parent.get(cid, []):
            walk(ch.id)

    walk(cat_id)
    return out


@router.get("/categories")
def list_categories(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    rows = db.query(ProductCategory).all()
    return build_tree(rows)


@router.post("/categories")
def create_category(
    body: CategoryIn,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    code = body.code.strip()
    name = body.name.strip()
    if not code or not name:
        raise HTTPException(400, "分类编码和名称必填")
    if db.query(ProductCategory).filter(ProductCategory.code == code).first():
        raise HTTPException(400, "分类编码已存在")
    if body.parent_id and not db.get(ProductCategory, body.parent_id):
        raise HTTPException(400, "上级分类不存在")
    row = ProductCategory(code=code, name=name, parent_id=body.parent_id, sort=body.sort)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name": row.name, "parent_id": row.parent_id}


@router.patch("/categories/{category_id}")
def update_category(
    category_id: int,
    body: CategoryIn,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    row = db.get(ProductCategory, category_id)
    if not row:
        raise HTTPException(404, "分类不存在")
    code = body.code.strip()
    name = body.name.strip()
    if not code or not name:
        raise HTTPException(400, "分类编码和名称必填")
    exists = db.query(ProductCategory).filter(ProductCategory.code == code, ProductCategory.id != category_id).first()
    if exists:
        raise HTTPException(400, "分类编码已存在")
    if body.parent_id == category_id:
        raise HTTPException(400, "不能把分类设为自己的下级")
    row.code = code
    row.name = name
    row.parent_id = body.parent_id
    row.sort = body.sort
    db.commit()
    return {"ok": True}


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    row = db.get(ProductCategory, category_id)
    if not row:
        raise HTTPException(404, "分类不存在")
    if db.query(ProductCategory).filter(ProductCategory.parent_id == category_id).first():
        raise HTTPException(400, "请先删除下级分类")
    if db.query(Product).filter(Product.category_id == category_id).first():
        raise HTTPException(400, "分类下还有产品，不能删除")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("")
def list_products(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    q: str = "",
    sku: str = "",
    status: str = "",
    category_id: Optional[int] = None,
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    query = db.query(Product)
    if q:
        like = f"%{q}%"
        query = query.filter((Product.sku.like(like)) | (Product.name.like(like)))
    if sku:
        query = query.filter(Product.sku.like(f"%{sku}%"))
    if status:
        query = query.filter(Product.status == status)
    if active_only:
        query = query.filter(Product.status == "active")
    if category_id:
        cats = db.query(ProductCategory).all()
        ids = descendant_ids(cats, category_id)
        query = query.filter(Product.category_id.in_(ids))
    total = query.count()
    rows = (
        query.options(joinedload(Product.category))
        .order_by(Product.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    show_cost = user.role in ("admin", "purchase")
    return {
        "items": [product_out(p, show_cost) for p in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("")
def create_product(
    body: ProductIn,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    if db.query(Product).filter(Product.sku == body.sku).first():
        raise HTTPException(400, "产品ID已存在")
    if body.status not in ("active", "disabled"):
        raise HTTPException(400, "状态无效")
    if body.category_id and not db.get(ProductCategory, body.category_id):
        raise HTTPException(400, "产品分类不存在")
    data = body.model_dump()
    if not data.get("primary_unit"):
        data["primary_unit"] = data.get("unit") or "pcs"
    if not data.get("sales_unit"):
        data["sales_unit"] = data.get("unit") or "pcs"
    p = Product(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return product_out(p, True)


@router.patch("/{product_id}")
def update_product(
    product_id: int,
    body: ProductIn,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "产品不存在")
    exists = db.query(Product).filter(Product.sku == body.sku, Product.id != product_id).first()
    if exists:
        raise HTTPException(400, "产品ID已存在")
    if body.category_id and not db.get(ProductCategory, body.category_id):
        raise HTTPException(400, "产品分类不存在")
    data = body.model_dump()
    if not data.get("primary_unit"):
        data["primary_unit"] = data.get("unit") or "pcs"
    if not data.get("sales_unit"):
        data["sales_unit"] = data.get("unit") or "pcs"
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return product_out(p, True)


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "产品不存在")
    used = db.query(InquiryLine).filter(InquiryLine.product_id == product_id).first()
    if used:
        p.status = "disabled"
        db.commit()
        return {"ok": True, "action": "disabled", "message": "产品已被询价引用，已改为停用"}
    db.delete(p)
    db.commit()
    return {"ok": True, "action": "deleted", "message": "已删除"}
