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
from app.core.version import APP_VERSION
from app.db.init_db import init_db
from app.db.models import ProviderType
from app.db.session import SessionLocal
from app.services.sync_scheduler import run_background_sync_loop, stop_background_task
from app.services.device_admin_service import purge_demo_devices, restore_non_demo_deleted_devices
from app.services.runtime_config_service import bootstrap_runtime_settings, get_runtime_config
from app.services.runtime_diagnostics_service import ensure_runtime_startup_ready, get_runtime_diagnostics


settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        runtime = bootstrap_runtime_settings(db)
        ensure_runtime_startup_ready(db)
        if runtime.provider != ProviderType.DEMO.value:
            restore_non_demo_deleted_devices(db)
            purge_demo_devices(db)
    stop_event = asyncio.Event()
    background_task = asyncio.create_task(run_background_sync_loop(stop_event), name="smartlife-background-sync")
    app.state.smartlife_sync_stop_event = stop_event
    app.state.smartlife_sync_task = background_task
    try:
        yield
    finally:
        await stop_background_task(background_task, stop_event)


app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(web_router)
app.include_router(api_router)


@app.get("/health")
def root_health():
    with SessionLocal() as db:
        runtime = get_runtime_config(db)
        diagnostics = get_runtime_diagnostics(db)
    return {
        "status": diagnostics.status,
        "service": settings.app_name,
        "version": APP_VERSION,
        "provider": runtime.provider,
        "provider_configured": diagnostics.provider_configured,
        "tariff_mode": runtime.tariff_mode,
        "tariff_display": runtime.tariff_display,
        "tariff_active_from": runtime.tariff_effective_from,
        "tariff_history_count": diagnostics.tariff_history_count,
        "tariff_change_target_month": diagnostics.tariff_change_target_month,
        "next_tariff_effective_from": diagnostics.next_tariff_effective_from,
        "timezone": settings.timezone,
        "background_sync_enabled": settings.smartlife_background_sync_enabled,
        "sync_on_startup": settings.smartlife_sync_on_startup,
        "sync_interval_seconds": settings.smartlife_sync_interval_seconds,
        "backup_keep_last": runtime.backup_keep_last,
        "backup_auto_prune_enabled": runtime.backup_auto_prune_enabled,
        "database_ready": diagnostics.schema_ready,
        "runtime_ready": diagnostics.runtime_ready,
        "schema_issues": diagnostics.schema_issues,
        "warnings": diagnostics.warnings,
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
