from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import ROLE_LABEL, require_roles
from app.core.utils import fmt_dt
from app.db.database import get_db
from app.db.models import OperationLog, User

router = APIRouter(prefix="/api/audit-logs", tags=["audit-logs"])

MODULES = ("账户", "产品库", "询价单", "销售订单", "采购订单", "财务管理", "问题反馈", "系统")


def serialize(row: OperationLog) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": row.username,
        "user_name": row.user_name,
        "role": row.role,
        "role_label": ROLE_LABEL.get(row.role, row.role or "未登录"),
        "module": row.module,
        "action": row.action,
        "method": row.method,
        "path": row.path,
        "target": row.target,
        "detail": row.detail,
        "ip": row.ip,
        "status_code": row.status_code,
        "success": row.success,
        "created_at": fmt_dt(row.created_at),
    }


@router.get("")
def list_audit_logs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("admin"))],
    q: str = "",
    role: str = "",
    module: str = "",
    success: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    qry = db.query(OperationLog)
    text = (q or "").strip()
    if text:
        like = f"%{text}%"
        qry = qry.filter(
            or_(
                OperationLog.username.like(like),
                OperationLog.user_name.like(like),
                OperationLog.action.like(like),
                OperationLog.target.like(like),
                OperationLog.detail.like(like),
                OperationLog.path.like(like),
            )
        )
    if role:
        qry = qry.filter(OperationLog.role == role)
    if module:
        qry = qry.filter(OperationLog.module == module)
    if success == "1":
        qry = qry.filter(OperationLog.success.is_(True))
    elif success == "0":
        qry = qry.filter(OperationLog.success.is_(False))
    total = qry.count()
    rows = qry.order_by(OperationLog.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "modules": list(MODULES),
        "items": [serialize(r) for r in rows],
    }
