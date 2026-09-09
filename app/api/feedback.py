from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.auth import ROLE_LABEL, get_current_user
from app.db.database import get_db
from app.db.models import Feedback, User
from app.core.utils import fmt_dt, next_no

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

KIND = {"bug": "缺陷", "suggestion": "建议"}
SEVERITY = {"normal": "一般", "high": "严重"}
STATUS = {"open": "待处理", "done": "已处理"}


class FeedbackIn(BaseModel):
    kind: str = "bug"
    severity: str = "normal"
    title: str = Field(min_length=1, max_length=200)
    body: str = ""


class FeedbackPatch(BaseModel):
    status: Optional[str] = None


def serialize(row: Feedback, user: User) -> dict:
    return {
        "id": row.id,
        "no": row.no,
        "kind": row.kind,
        "kind_label": KIND.get(row.kind, row.kind),
        "severity": row.severity,
        "severity_label": SEVERITY.get(row.severity, row.severity),
        "title": row.title,
        "body": row.body or "",
        "status": row.status,
        "status_label": STATUS.get(row.status, row.status),
        "creator_id": row.creator_id,
        "creator_name": row.creator.name if row.creator else "",
        "creator_role": ROLE_LABEL.get(row.creator.role, row.creator.role) if row.creator else "",
        "created_at": fmt_dt(row.created_at),
        "can_resolve": user.role == "admin" and row.status == "open",
    }


@router.get("")
def list_feedback(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    status: str = "",
    kind: str = "",
):
    q = db.query(Feedback).options(joinedload(Feedback.creator))
    if user.role != "admin":
        q = q.filter(Feedback.creator_id == user.id)
    if status in STATUS:
        q = q.filter(Feedback.status == status)
    if kind in KIND:
        q = q.filter(Feedback.kind == kind)
    rows = q.order_by(Feedback.id.desc()).all()
    return [serialize(r, user) for r in rows]


@router.post("")
def create_feedback(
    body: FeedbackIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if body.kind not in KIND:
        raise HTTPException(400, "类型仅为缺陷或建议")
    if body.severity not in SEVERITY:
        raise HTTPException(400, "严重程度仅为一般或严重")
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "请填写标题")
    row = Feedback(
        no=next_no(db, Feedback, "FB"),
        creator_id=user.id,
        kind=body.kind,
        severity=body.severity,
        title=title,
        body=(body.body or "").strip(),
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    row = db.query(Feedback).options(joinedload(Feedback.creator)).filter(Feedback.id == row.id).first()
    return serialize(row, user)


@router.patch("/{fid}")
def patch_feedback(
    fid: int,
    body: FeedbackPatch,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    row = db.query(Feedback).options(joinedload(Feedback.creator)).filter(Feedback.id == fid).first()
    if not row:
        raise HTTPException(404, "反馈不存在")
    if user.role != "admin":
        raise HTTPException(403, "没有权限处理该反馈")
    if body.status:
        if body.status not in STATUS:
            raise HTTPException(400, "状态无效")
        row.status = body.status
    db.commit()
    row = db.query(Feedback).options(joinedload(Feedback.creator)).filter(Feedback.id == fid).first()
    return serialize(row, user)
