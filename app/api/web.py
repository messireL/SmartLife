from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import format_local_datetime
from app.db.models import BucketType, Device, DeviceStatusSnapshot, EnergySample, SyncRun, SyncRunTrigger
from app.db.session import get_db
from app.services.dashboard_service import get_dashboard_summary, get_sync_overview
from app.services.sync_runner import SyncAlreadyRunningError, run_sync_job

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
templates.env.globals["app_settings"] = settings
templates.env.filters["localdt"] = lambda value: format_local_datetime(value)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    summary = get_dashboard_summary(db)
    sync_overview = get_sync_overview(db)
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

    daily = db.execute(
        select(EnergySample)
        .where(EnergySample.device_id == device.id, EnergySample.bucket_type == BucketType.DAY)
        .order_by(EnergySample.period_start.desc())
        .limit(30)
    ).scalars().all()

    monthly = db.execute(
        select(EnergySample)
        .where(EnergySample.device_id == device.id, EnergySample.bucket_type == BucketType.MONTH)
        .order_by(EnergySample.period_start.desc())
        .limit(12)
    ).scalars().all()

    snapshots = db.execute(
        select(DeviceStatusSnapshot)
        .where(DeviceStatusSnapshot.device_id == device.id)
        .order_by(DeviceStatusSnapshot.recorded_at.desc(), DeviceStatusSnapshot.id.desc())
        .limit(20)
    ).scalars().all()

    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {
            "request": request,
            "device": device,
            "daily": daily,
            "monthly": monthly,
            "snapshots": snapshots,
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
