from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
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


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def apply_created_at_range(query, column, date_from: str = "", date_to: str = ""):
    """按北京时间自然日筛选 DateTime 列（库中按 UTC 存储）。"""
    d0, d1 = parse_iso_date(date_from), parse_iso_date(date_to)
    if d0:
        start = datetime(d0.year, d0.month, d0.day, tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(column >= start)
    if d1:
        end = datetime(d1.year, d1.month, d1.day, tzinfo=TZ) + timedelta(days=1)
        end = end.astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(column < end)
    return query


def apply_doc_date_range(query, model, date_from: str = "", date_to: str = ""):
    """单据日期优先，没有则用创建日。"""
    from sqlalchemy import Date, cast, func

    d0, d1 = parse_iso_date(date_from), parse_iso_date(date_to)
    if not d0 and not d1:
        return query
    effective = func.coalesce(model.doc_date, cast(model.created_at, Date))
    if d0:
        query = query.filter(effective >= d0)
    if d1:
        query = query.filter(effective <= d1)
    return query


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
