from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from app.core.auth import get_current_user
from app.core.fx import rmb_rates, rates_payload
from app.db.models import User

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

CITIES = (
    ("北京", "Asia/Shanghai", "中国"),
    ("东京", "Asia/Tokyo", "日本"),
    ("迪拜", "Asia/Dubai", "中东"),
    ("伦敦", "Europe/London", "英国"),
    ("汉堡", "Europe/Berlin", "德国 / 欧盟"),
    ("纽约", "America/New_York", "美国东部"),
    ("洛杉矶", "America/Los_Angeles", "美国西部"),
    ("协调世界时", "UTC", "UTC"),
)

WEEKDAY = "一二三四五六日"


def _offset_label(dt: datetime) -> str:
    off = dt.utcoffset()
    if off is None:
        return "UTC"
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    h, m = divmod(total, 60)
    return f"UTC{sign}{h:02d}" + (f":{m:02d}" if m else "")


def _vs_beijing(dt: datetime, beijing: datetime) -> str:
    a = dt.utcoffset()
    b = beijing.utcoffset()
    if a is None or b is None:
        return ""
    hours = (a - b).total_seconds() / 3600
    if abs(hours) < 0.01:
        return "与北京同时"
    sign = "+" if hours > 0 else ""
    if hours == int(hours):
        return f"比北京 {sign}{int(hours)} 小时"
    return f"比北京 {sign}{hours:g} 小时"


def _work_status(dt: datetime) -> dict:
    wd = dt.weekday()
    hour = dt.hour + dt.minute / 60
    if wd >= 5:
        return {"work": False, "label": "周末"}
    if 9 <= hour < 18:
        return {"work": True, "label": "工作时间"}
    return {"work": False, "label": "非工作时间"}


def world_clocks() -> list[dict]:
    now = datetime.now(timezone.utc)
    beijing = now.astimezone(ZoneInfo("Asia/Shanghai"))
    out = []
    for city, tz, region in CITIES:
        dt = now.astimezone(ZoneInfo(tz))
        st = _work_status(dt)
        out.append(
            {
                "city": city,
                "tz": tz,
                "region": region,
                "time": dt.strftime("%H:%M:%S"),
                "date": dt.strftime("%m-%d"),
                "weekday": "周" + WEEKDAY[dt.weekday()],
                "offset": _offset_label(dt),
                "vs_beijing": _vs_beijing(dt, beijing),
                "work": st["work"],
                "work_label": st["label"],
            }
        )
    return out


@router.get("")
def assistant_snapshot(
    _: Annotated[User, Depends(get_current_user)],
    refresh: bool = Query(False),
):
    if refresh:
        rmb_rates(force=True)
    fx = rates_payload()
    rates = rmb_rates().get("rates") or {}
    usd = rates.get("USD")
    eur = rates.get("EUR")
    return {
        "fx": fx,
        "quotes": [
            {
                "code": "USD",
                "name": "美元",
                "pair": "USD / RMB",
                "rate": f"{usd:.4f}" if usd is not None else "—",
                "per": "1 美元",
            },
            {
                "code": "EUR",
                "name": "欧元",
                "pair": "EUR / RMB",
                "rate": f"{eur:.4f}" if eur is not None else "—",
                "per": "1 欧元",
            },
        ],
        "clocks": world_clocks(),
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
