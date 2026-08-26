from __future__ import annotations

import json
import time
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

CURRENCIES = ("RMB", "USD", "EUR")
_CACHE_TTL = 3600
_cache: dict = {"at": 0.0, "rates": {"USD": Decimal("7.20"), "EUR": Decimal("7.80")}, "as_of": "", "source": "fallback"}


def norm_ccy(code: Optional[str]) -> str:
    c = (code or "RMB").strip().upper()
    if c in ("CNY", "RMB"):
        return "RMB"
    return c


def _dec(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _http_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "lafa-trade/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_live() -> Optional[tuple[dict[str, Decimal], str, str]]:
    try:
        data = _http_json("https://open.er-api.com/v6/latest/CNY")
        if data.get("result") == "success" and isinstance(data.get("rates"), dict):
            rates = {}
            for ccy in ("USD", "EUR"):
                per_cny = data["rates"].get(ccy)
                if per_cny:
                    rates[ccy] = _dec(Decimal("1") / Decimal(str(per_cny)))
            if rates:
                return rates, str(data.get("time_last_update_utc") or ""), "open.er-api.com"
    except Exception:
        pass
    try:
        usd = _http_json("https://api.frankfurter.app/latest?from=USD&to=CNY")
        eur = _http_json("https://api.frankfurter.app/latest?from=EUR&to=CNY")
        rates = {}
        if usd.get("rates", {}).get("CNY"):
            rates["USD"] = _dec(usd["rates"]["CNY"])
        if eur.get("rates", {}).get("CNY"):
            rates["EUR"] = _dec(eur["rates"]["CNY"])
        if rates:
            return rates, str(usd.get("date") or ""), "frankfurter.app"
    except Exception:
        pass
    return None


def rmb_rates(force: bool = False) -> dict:
    now = time.time()
    if not force and _cache["at"] and now - _cache["at"] < _CACHE_TTL:
        return _cache
    live = _fetch_live()
    if live:
        rates, as_of, source = live
        merged = {**_cache["rates"], **rates}
        _cache.update({"at": now, "rates": merged, "as_of": as_of, "source": source})
    elif not _cache["at"]:
        _cache["at"] = now
    return _cache


def money2(amount) -> Decimal:
    return Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_rmb(amount, currency: Optional[str], rates: Optional[dict] = None) -> Decimal:
    amt = money2(amount)
    ccy = norm_ccy(currency)
    if amt == 0 or ccy == "RMB":
        return amt
    table = (rates or rmb_rates()).get("rates") or {}
    rate = table.get(ccy)
    if not rate:
        return amt
    return money2(amt * Decimal(str(rate)))


def rates_payload() -> dict:
    data = rmb_rates()
    return {
        "base": "RMB",
        "as_of": data.get("as_of") or "",
        "source": data.get("source") or "",
        "rates": {k: str(v) for k, v in (data.get("rates") or {}).items()},
    }
