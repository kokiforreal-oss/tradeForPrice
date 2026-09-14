"""HTTP 路由：按业务拆分，在此统一挂到 FastAPI。"""

from fastapi import FastAPI

from app.api import (
    audit_logs,
    auth,
    crypto,
    customers,
    dashboard,
    factories,
    feedback,
    finance,
    inquiries,
    orders,
    products,
    purchase_orders,
)

_MODULES = (
    auth,
    crypto,
    products,
    customers,
    factories,
    inquiries,
    orders,
    purchase_orders,
    finance,
    dashboard,
    feedback,
    audit_logs,
)


def register_routers(app: FastAPI) -> None:
    for mod in _MODULES:
        app.include_router(mod.router)
