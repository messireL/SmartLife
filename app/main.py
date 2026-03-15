from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.api import router as api_router
from app.api.web import router as web_router
from app.core.config import get_settings
from app.db.init_db import init_db
from app.services.sync_scheduler import run_background_sync_loop, stop_background_task


settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop_event = asyncio.Event()
    background_task = None
    if settings.smartlife_background_sync_enabled or settings.smartlife_sync_on_startup:
        background_task = asyncio.create_task(run_background_sync_loop(stop_event), name="smartlife-background-sync")
    app.state.smartlife_sync_stop_event = stop_event
    app.state.smartlife_sync_task = background_task
    try:
        yield
    finally:
        await stop_background_task(background_task, stop_event)


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(web_router)
app.include_router(api_router)


@app.get("/health")
def root_health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "provider": settings.smartlife_provider,
        "timezone": settings.timezone,
        "background_sync_enabled": settings.smartlife_background_sync_enabled,
        "sync_on_startup": settings.smartlife_sync_on_startup,
        "sync_interval_seconds": settings.smartlife_sync_interval_seconds,
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon_file():
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon_file():
    return FileResponse(STATIC_DIR / "icon-192.png", media_type="image/png")


@app.get("/icon.svg", include_in_schema=False)
def app_icon_file():
    return FileResponse(STATIC_DIR / "icon.svg", media_type="image/svg+xml")


@app.get("/site.webmanifest", include_in_schema=False)
def site_manifest_file():
    return FileResponse(STATIC_DIR / "site.webmanifest", media_type="application/manifest+json")
