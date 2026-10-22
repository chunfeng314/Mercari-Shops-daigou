from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import automation, china_sourcing, items, japan_selection, mercari_listing, orders, source_images
from app.automation.service import AutomationService
from app.site_catalog import CHINA_SITES, JAPAN_SITES


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    service = AutomationService()
    _.state.automation = service
    service.start()
    try:
        yield
    finally:
        service.stop()


app = FastAPI(
    title="煤炉代购工具",
    description="日本选品 → 中国货源核验 → Mercari Shops 上架；成交后采购履约",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(japan_selection.router)
app.include_router(china_sourcing.router)
app.include_router(mercari_listing.router)
app.include_router(orders.router)
app.include_router(items.router)
app.include_router(source_images.router)
app.include_router(automation.router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health", tags=["系统"])
def health() -> dict:
    return {"status": "ok", "japan_sites": len(JAPAN_SITES), "china_sites": len(CHINA_SITES)}
