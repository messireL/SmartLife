from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import format_local_date, format_local_datetime
from app.db.models import Device, SyncRun, SyncRunTrigger
from app.db.session import get_db
from app.services.dashboard_service import (
    get_dashboard_panels,
    get_dashboard_summary,
    get_device_dashboard,
    get_sync_overview,
)
from app.services.sync_runner import SyncAlreadyRunningError, run_sync_job

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
templates.env.globals["app_settings"] = settings
templates.env.filters["localdt"] = lambda value: format_local_datetime(value)
templates.env.filters["localdate"] = lambda value: format_local_date(value)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    summary = get_dashboard_summary(db)
    sync_overview = get_sync_overview(db)
    dashboard_panels = get_dashboard_panels(db)
    recent_sync_runs = db.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(8)
    ).scalars().all()
    devices = db.execute(select(Device).order_by(Device.room_name, Device.name)).scalars().all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "summary": summary,
            "sync_overview": sync_overview,
            "dashboard_panels": dashboard_panels,
            "recent_sync_runs": recent_sync_runs,
            "devices": devices,
            "request": request,
            "flash": request.query_params.get("flash"),
            "settings": settings,
        },
    )


@router.get("/devices/{device_id}", response_class=HTMLResponse)
def device_detail(device_id: int, request: Request, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        return templates.TemplateResponse(request, "not_found.html", {"request": request}, status_code=404)

    view_model = get_device_dashboard(db, device)
    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {
            "request": request,
            "device": device,
            "daily": view_model["daily"],
            "monthly": view_model["monthly"],
            "snapshots": view_model["snapshots"],
            "device_view": view_model,
            "settings": settings,
        },
    )


@router.post("/actions/sync-provider")
def sync_provider_action():
    try:
        outcome = run_sync_job(trigger=SyncRunTrigger.MANUAL, fail_if_running=True)
        result = outcome["result"]
        flash = (
            f"Синхронизация завершена: provider={result['provider']} devices={result['devices_total']} "
            f"daily={result['daily_samples_total']} monthly={result['monthly_samples_total']} "
            f"snapshots={result['snapshots_total']} aggregated={result['aggregated_energy_updates']} "
            f"за {outcome['duration_ms']} ms"
        )
    except SyncAlreadyRunningError:
        flash = "Синхронизация уже выполняется в фоне. Подожди завершения текущего цикла."
    except Exception as exc:  # noqa: BLE001
        flash = f"Sync failed: {exc}"
    return RedirectResponse(url=f"/?flash={quote_plus(flash)}", status_code=303)
