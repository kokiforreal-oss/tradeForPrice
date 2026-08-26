"""HTTP 路由：按业务拆分，在此统一挂到 FastAPI。"""

from fastapi import FastAPI

from app.api import assistant, auth, crypto, dashboard, finance, inquiries, orders, products, purchase_orders

_MODULES = (
    auth,
    crypto,
    products,
    inquiries,
    orders,
    purchase_orders,
    finance,
    dashboard,
    assistant,
)


def register_routers(app: FastAPI) -> None:
    for mod in _MODULES:
        app.include_router(mod.router)
