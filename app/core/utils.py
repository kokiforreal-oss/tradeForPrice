from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.e2e import is_enc

TZ = ZoneInfo("Asia/Shanghai")


def to_float(v):
    if v is None or v == "":
        return None
    if is_enc(v):
        return v
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def next_no(db: Session, model, prefix: str) -> str:
    today = datetime.now(TZ).strftime("%Y%m%d")
    head = f"{prefix}-{today}-"
    last = (
        db.query(model)
        .filter(model.no.like(f"{head}%"))
        .order_by(model.no.desc())
        .first()
    )
    seq = 1 if not last else int(str(last.no).split("-")[-1]) + 1
    return f"{head}{seq:04d}"


def fmt_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
        else:
            v = v.astimezone(TZ)
        return v.strftime("%Y-%m-%d %H:%M")
    return v.isoformat()
