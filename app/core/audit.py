from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.core.auth import ROLE_LABEL
from app.db.database import SessionLocal
from app.db.models import OperationLog, User

log = logging.getLogger("uvicorn.error")

_SKIP_PREFIXES = ("/static/", "/uploads/", "/api/docs", "/api/redoc", "/api/openapi")
_SKIP_PATHS = {"/api/health", "/favicon.ico"}
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_EXTRA_GET = ("/export",)

_RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    ("POST", re.compile(r"^/api/auth/login$"), "登录", "账户"),
    ("POST", re.compile(r"^/api/users$"), "新增用户", "账户"),
    ("PATCH", re.compile(r"^/api/users/\d+$"), "修改用户", "账户"),
    ("POST", re.compile(r"^/api/products/categories$"), "新增产品分类", "产品库"),
    ("PATCH", re.compile(r"^/api/products/categories/\d+$"), "修改产品分类", "产品库"),
    ("DELETE", re.compile(r"^/api/products/categories/\d+$"), "删除产品分类", "产品库"),
    ("POST", re.compile(r"^/api/products/import$"), "导入产品", "产品库"),
    ("GET", re.compile(r"^/api/products/export$"), "导出产品", "产品库"),
    ("POST", re.compile(r"^/api/products$"), "新增产品", "产品库"),
    ("PATCH", re.compile(r"^/api/products/\d+$"), "修改产品", "产品库"),
    ("DELETE", re.compile(r"^/api/products/\d+$"), "删除产品", "产品库"),
    ("POST", re.compile(r"^/api/inquiries$"), "新建询价", "询价单"),
    ("PATCH", re.compile(r"^/api/inquiries/\d+$"), "修改询价", "询价单"),
    ("POST", re.compile(r"^/api/inquiries/\d+/quotes$"), "提交报价", "询价单"),
    ("POST", re.compile(r"^/api/inquiries/\d+/select-quote$"), "选用报价", "询价单"),
    ("POST", re.compile(r"^/api/inquiries/\d+/requote$"), "申请重新报价", "询价单"),
    ("POST", re.compile(r"^/api/inquiries/\d+/win$"), "询价成交", "询价单"),
    ("POST", re.compile(r"^/api/inquiries/\d+/close$"), "关闭询价", "询价单"),
    ("DELETE", re.compile(r"^/api/inquiries/\d+$"), "删除询价", "询价单"),
    ("POST", re.compile(r"^/api/orders$"), "新建销售单", "销售订单"),
    ("POST", re.compile(r"^/api/orders/\d+/save$"), "保存销售单", "销售订单"),
    ("POST", re.compile(r"^/api/orders/\d+/submit$"), "提交销售单审核", "销售订单"),
    ("POST", re.compile(r"^/api/orders/\d+/withdraw$"), "撤回销售单", "销售订单"),
    ("POST", re.compile(r"^/api/orders/\d+/audit$"), "审核销售单", "销售订单"),
    ("POST", re.compile(r"^/api/orders/\d+/submit-contract$"), "提交销售合同", "销售订单"),
    ("DELETE", re.compile(r"^/api/orders/\d+$"), "删除销售单", "销售订单"),
    ("POST", re.compile(r"^/api/purchase-orders$"), "新建采购单", "采购订单"),
    ("POST", re.compile(r"^/api/purchase-orders/\d+/save$"), "保存采购单", "采购订单"),
    ("POST", re.compile(r"^/api/purchase-orders/\d+/submit$"), "提交采购单审核", "采购订单"),
    ("POST", re.compile(r"^/api/purchase-orders/\d+/withdraw$"), "撤回采购单", "采购订单"),
    ("POST", re.compile(r"^/api/purchase-orders/\d+/audit$"), "审核采购单", "采购订单"),
    ("POST", re.compile(r"^/api/purchase-orders/\d+/logistics$"), "填写采购物流", "采购订单"),
    ("POST", re.compile(r"^/api/purchase-orders/\d+/advance$"), "推进采购履约", "采购订单"),
    ("DELETE", re.compile(r"^/api/purchase-orders/\d+$"), "删除采购单", "采购订单"),
    ("POST", re.compile(r"^/api/finance/vouchers$"), "新建收付款单", "财务管理"),
    ("PUT", re.compile(r"^/api/finance/vouchers/\d+$"), "保存收付款单", "财务管理"),
    ("POST", re.compile(r"^/api/finance/receipts$"), "登记收款", "财务管理"),
    ("POST", re.compile(r"^/api/finance/payments$"), "登记付款", "财务管理"),
    ("POST", re.compile(r"^/api/finance/invoices$"), "登记发票", "财务管理"),
    ("POST", re.compile(r"^/api/finance/writeoffs$"), "核销", "财务管理"),
    ("POST", re.compile(r"^/api/feedback$"), "提交问题反馈", "问题反馈"),
    ("PATCH", re.compile(r"^/api/feedback/\d+$"), "处理问题反馈", "问题反馈"),
]


def should_audit(method: str, path: str) -> bool:
    if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PREFIXES):
        return False
    if not path.startswith("/api/"):
        return False
    if path.startswith("/api/audit-logs"):
        return False
    if method in _MUTATING:
        return True
    if method == "GET" and any(path.endswith(s) for s in _EXTRA_GET):
        return True
    return False


def describe(method: str, path: str, body: Any) -> tuple[str, str]:
    action, module = f"{method} {path}", "系统"
    for m, pat, act, mod in _RULES:
        if method == m and pat.match(path):
            action, module = act, mod
            break
    if module == "账户" and method == "PATCH" and isinstance(body, dict):
        if "password" in body and body.get("password"):
            action = "修改密码"
        elif "is_active" in body:
            action = "启用账号" if body.get("is_active") else "停用账号"
    if method == "POST" and path.endswith("/audit") and isinstance(body, dict):
        act = str(body.get("action") or "").strip()
        if module == "销售订单":
            if act == "reject":
                action = "驳回销售单"
            elif act == "pass":
                action = "通过销售单"
        elif module == "采购订单":
            if act == "reject":
                action = "驳回采购单"
            elif act == "pass":
                action = "通过采购单"
    return action, module


def target_of(path: str) -> str:
    found = re.findall(r"/(\d+)(?:/|$)", path)
    return found[0] if found else ""


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def _parse_body(raw: bytes, content_type: str) -> Any:
    if not raw or "multipart/" in (content_type or "").lower():
        return None
    if len(raw) > 8192:
        return None
    try:
        text = raw.decode("utf-8")
        return json.loads(text)
    except Exception:
        return None


def _detail(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    bits: list[str] = []
    for key, label in (
        ("username", "用户名"),
        ("name", "姓名"),
        ("title", "标题"),
        ("status", "状态"),
        ("kind", "类型"),
        ("sku", "SKU"),
    ):
        val = body.get(key)
        if val not in (None, ""):
            bits.append(f"{label} {val}")
    return "；".join(bits)[:500]


def _user_from_auth(db, request: Request, body: Any) -> Optional[User]:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        try:
            data = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
            user = db.get(User, int(data["sub"]))
            if user:
                return user
        except Exception:
            pass
    if isinstance(body, dict):
        uname = str(body.get("username") or "").strip()
        if uname:
            return db.query(User).filter(User.username == uname).first()
    return None


def persist_audit(request: Request, status_code: int, raw_body: bytes) -> None:
    method = request.method.upper()
    path = request.url.path
    if not should_audit(method, path):
        return
    body = _parse_body(raw_body, request.headers.get("content-type") or "")
    action, module = describe(method, path, body)
    db = SessionLocal()
    try:
        user = _user_from_auth(db, request, body)
        username = (user.username if user else "") or (
            str(body.get("username") or "").strip() if isinstance(body, dict) else ""
        )
        row = OperationLog(
            user_id=user.id if user else None,
            username=username[:64],
            user_name=(user.name if user else "")[:64],
            role=user.role if user else "",
            module=module,
            action=action,
            method=method,
            path=path[:200],
            target=target_of(path),
            detail=_detail(body),
            ip=client_ip(request),
            status_code=status_code,
            success=200 <= status_code < 400,
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("write operation log failed")
    finally:
        db.close()


class OperationAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        raw = b""
        method = request.method.upper()
        path = request.url.path
        audit = should_audit(method, path)
        if audit:
            ct = (request.headers.get("content-type") or "").lower()
            if "multipart/" not in ct:
                try:
                    raw = await request.body()
                except Exception:
                    raw = b""

                async def receive() -> dict:
                    return {"type": "http.request", "body": raw, "more_body": False}

                request = Request(request.scope, receive)
        response = await call_next(request)
        if audit:
            try:
                persist_audit(request, response.status_code, raw)
            except Exception:
                log.exception("operation audit middleware failed")
        return response
