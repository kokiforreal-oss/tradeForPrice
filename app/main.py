"""拉法国际外贸系统 — FastAPI 入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import register_routers
from app.config import BASE_DIR, UPLOAD_DIR
from app.db.database import Base, SessionLocal, engine, ensure_schema, preserve_org_key
from app.db.seed import ensure_catalog, seed

STATIC = BASE_DIR / "app" / "static"


def init_db():
    import app.db.models  # noqa: F401  注册全部表，供 create_all

    Base.metadata.create_all(bind=engine, checkfirst=True)
    preserve_org_key()
    ensure_schema()
    db = SessionLocal()
    try:
        seed(db)
        ensure_catalog(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="拉法国际外贸系统", docs_url="/api/docs", lifespan=lifespan)
register_routers(app)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "static/", "uploads/")):
        raise HTTPException(404, "Not Found")
    return FileResponse(STATIC / "index.html")
