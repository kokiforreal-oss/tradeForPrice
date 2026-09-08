from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.core.auth import get_current_user, require_roles
from app.core.e2e import MoneyIn
from app.core.product_io import (
    MAX_IMPORT_BYTES,
    build_csv,
    build_template,
    build_xlsx,
    parse_upload,
)
from app.core.utils import fmt_dt, to_float
from app.db.database import get_db
from app.db.models import InquiryLine, Product, ProductCategory, User

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


def _status_label(status: str) -> str:
    return "启用" if status == "active" else "停用"


def _parse_status(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("", "active", "启用", "在用", "正常"):
        return "active"
    if v in ("disabled", "停用", "禁用", "失效"):
        return "disabled"
    raise ValueError("状态只能是启用或停用")


def _export_row(p: Product, show_cost: bool) -> dict:
    cat = p.category
    row = {
        "sku": p.sku,
        "name": p.name,
        "spec": p.spec or "",
        "category_code": cat.code if cat else "",
        "category_name": cat.name if cat else "",
        "product_type": p.product_type or "实物",
        "pricing_method": p.pricing_method or "固定价",
        "unit": p.unit or "pcs",
        "primary_unit": p.primary_unit or p.unit or "pcs",
        "aux_unit": p.aux_unit or "",
        "sales_unit": p.sales_unit or p.unit or "pcs",
        "status": _status_label(p.status),
        "remark": p.remark or "",
    }
    if show_cost:
        cost = to_float(p.cost_price)
        row["cost_price"] = "" if cost is None else cost
    return row


def _filtered_products(
    db: Session,
    q: str = "",
    sku: str = "",
    status: str = "",
    category_id: Optional[int] = None,
    active_only: bool = False,
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
    return query.options(joinedload(Product.category))


def _file_name(prefix: str, ext: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    ascii_name = f"products-{stamp}.{ext}" if "模板" not in prefix else f"product-template-{stamp}.{ext}"
    utf_name = quote(f"{prefix}-{stamp}.{ext}")
    return f"attachment; filename={ascii_name}; filename*=UTF-8''{utf_name}"


def _resolve_category(db: Session, code: str, name: str, cache: dict) -> Optional[int]:
    code, name = (code or "").strip(), (name or "").strip()
    if not code and not name:
        return None
    key = ("code", code) if code else ("name", name)
    if key in cache:
        return cache[key]
    row = None
    if code:
        row = db.query(ProductCategory).filter(ProductCategory.code == code).first()
    if not row and name:
        row = db.query(ProductCategory).filter(ProductCategory.name == name).first()
    if not row:
        raise ValueError("产品分类不存在")
    cache[key] = row.id
    return row.id


def _apply_product_fields(p: Product, item: dict, category_id: Optional[int], allow_cost: bool) -> None:
    p.sku = item["sku"]
    p.name = item["name"]
    p.spec = item.get("spec") or ""
    p.product_type = item.get("product_type") or "实物"
    p.pricing_method = item.get("pricing_method") or "固定价"
    p.unit = item.get("unit") or "pcs"
    p.primary_unit = item.get("primary_unit") or p.unit
    p.aux_unit = item.get("aux_unit") or ""
    p.sales_unit = item.get("sales_unit") or p.unit
    p.category_id = category_id
    p.status = item["status"]
    p.remark = item.get("remark") or ""
    if allow_cost and "cost_price" in item:
        raw = item.get("cost_price")
        p.cost_price = None if raw in (None, "") else raw


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
    query = _filtered_products(db, q, sku, status, category_id, active_only)
    total = query.count()
    rows = query.order_by(Product.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    show_cost = user.role in ("admin", "purchase")
    return {
        "items": [product_out(p, show_cost) for p in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/export")
def export_products(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    q: str = "",
    sku: str = "",
    status: str = "",
    category_id: Optional[int] = None,
    fmt: str = Query(default="xlsx", alias="format"),
):
    show_cost = user.role in ("admin", "purchase")
    rows = [
        _export_row(p, show_cost)
        for p in _filtered_products(db, q, sku, status, category_id).order_by(Product.id.desc()).all()
    ]
    kind = (fmt or "xlsx").lower()
    if kind == "csv":
        data = build_csv(rows, show_cost)
        media = "text/csv; charset=utf-8"
        ext = "csv"
    else:
        data = build_xlsx(rows, show_cost)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    return Response(content=data, media_type=media, headers={"Content-Disposition": _file_name("产品库", ext)})


@router.get("/import-template")
def import_template(user: Annotated[User, Depends(get_current_user)]):
    show_cost = user.role in ("admin", "purchase")
    data = build_template(show_cost)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _file_name("产品导入模板", "xlsx")},
    )


@router.post("/import")
async def import_products(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "请选择要导入的文件")
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(400, "文件不能超过 8MB")
    try:
        items = parse_upload(file.filename or "", raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not items:
        raise HTTPException(400, "没有可导入的数据行")

    allow_cost = user.role in ("admin", "purchase")
    can_update = user.role == "admin"
    cats: dict = {}
    seen: set[str] = set()
    created = updated = 0
    errors: list[dict] = []

    for item in items:
        row_no = item.get("_row")
        sku = (item.get("sku") or "").strip()
        name = (item.get("name") or "").strip()
        try:
            if not sku or not name:
                raise ValueError("产品ID和产品名称必填")
            if sku in seen:
                raise ValueError("文件中产品ID重复")
            seen.add(sku)
            item["sku"], item["name"] = sku, name
            item["status"] = _parse_status(item.get("status") or "")
            if item.get("product_type") and item["product_type"] not in ("实物", "服务"):
                raise ValueError("商品类型只能是实物或服务")
            if item.get("pricing_method") and item["pricing_method"] not in ("固定价", "移动平均"):
                raise ValueError("计价方式只能是固定价或移动平均")
            category_id = _resolve_category(db, item.get("category_code") or "", item.get("category_name") or "", cats)
            if not allow_cost:
                item.pop("cost_price", None)
            existing = db.query(Product).filter(Product.sku == sku).first()
            if existing:
                if not can_update:
                    raise ValueError("产品ID已存在")
                _apply_product_fields(existing, item, category_id, allow_cost)
                updated += 1
            else:
                p = Product()
                _apply_product_fields(p, item, category_id, allow_cost)
                db.add(p)
                created += 1
        except ValueError as e:
            errors.append({"row": row_no, "sku": sku, "message": str(e)})
        except Exception:
            errors.append({"row": row_no, "sku": sku, "message": "该行数据无法保存，请检查格式"})

    if created or updated:
        db.commit()
    else:
        db.rollback()
    return {
        "created": created,
        "updated": updated,
        "failed": len(errors),
        "errors": errors[:30],
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
