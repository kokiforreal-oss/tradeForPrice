from __future__ import annotations

import base64
import hashlib
import hmac
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional, Union

from sqlalchemy import String, TypeDecorator

from app.config import DATA_DIR

MONEY_PREFIX = "m1."
NAME_PREFIX = "n1."
KEY_PATH = DATA_DIR / "e2e.key"
MoneyIn = Union[int, float, str]

_key: Optional[bytes] = None


def load_org_key() -> bytes:
    global _key
    if _key is not None:
        return _key
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        raw = KEY_PATH.read_bytes()
        if len(raw) != 32:
            raise RuntimeError("e2e.key 长度无效")
        _key = raw
        return _key
    raw = os.urandom(32)
    KEY_PATH.write_bytes(raw)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    _key = raw
    return _key


def org_key_b64() -> str:
    return base64.b64encode(load_org_key()).decode("ascii")


def is_enc(v: Any) -> bool:
    return isinstance(v, str) and (v.startswith(MONEY_PREFIX) or v.startswith(NAME_PREFIX))


def is_money_enc(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(MONEY_PREFIX)


def is_name_enc(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(NAME_PREFIX)


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _encrypt(plain: str, iv: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    token = AESGCM(load_org_key()).encrypt(iv, plain.encode("utf-8"), None)
    return _b64e(iv + token)


def _decrypt_blob(blob: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = _b64d(blob)
    iv, token = raw[:12], raw[12:]
    return AESGCM(load_org_key()).decrypt(iv, token, None).decode("utf-8")


def encrypt_money(plain: str) -> str:
    return MONEY_PREFIX + _encrypt(plain, os.urandom(12))


def encrypt_name(plain: str) -> str:
    text = (plain or "").strip()
    if not text:
        return ""
    iv = hmac.new(load_org_key(), b"n1|" + text.encode("utf-8"), hashlib.sha256).digest()[:12]
    return NAME_PREFIX + _encrypt(text, iv)


def decrypt_value(value: str) -> str:
    if value.startswith(MONEY_PREFIX):
        return _decrypt_blob(value[len(MONEY_PREFIX) :])
    if value.startswith(NAME_PREFIX):
        return _decrypt_blob(value[len(NAME_PREFIX) :])
    return value


def store_money(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if is_money_enc(value):
        return value
    return encrypt_money(f"{money(value):.2f}")


def store_name(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if is_name_enc(text):
        return text
    return encrypt_name(text)


def money(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0.00")
    if is_enc(v):
        v = decrypt_value(v)
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plain_name(v: Any) -> str:
    if v is None:
        return ""
    text = str(v).strip()
    if not text:
        return ""
    if is_name_enc(text):
        try:
            return decrypt_value(text)
        except Exception:
            return text
    return text


def names_equal(a: Any, b: Any) -> bool:
    return plain_name(a) == plain_name(b)


def to_api_money(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    if is_money_enc(v):
        return v
    return encrypt_money(f"{money(v):.2f}")


class EncryptedMoney(TypeDecorator):
    impl = String(512)
    cache_ok = False

    def __init__(self, allow_none: bool = True):
        super().__init__()
        self.allow_none = allow_none

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            if self.allow_none:
                return None
            return encrypt_money("0.00")
        return store_money(value)

    def process_result_value(self, value, dialect):
        return value


class EncryptedName(TypeDecorator):
    impl = String(512)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return store_name(value)

    def process_result_value(self, value, dialect):
        return value or ""
