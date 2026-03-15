from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import BucketType, Device, DeviceStatusSnapshot, EnergySample
from app.db.session import get_db
from app.services.dashboard_service import get_dashboard_summary
from app.services.sync_service import sync_from_provider

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    summary = get_dashboard_summary(db)
    devices = db.execute(select(Device).order_by(Device.room_name, Device.name)).scalars().all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "summary": summary,
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
def sync_provider_action(db: Session = Depends(get_db)):
    try:
        result = sync_from_provider(db)
        flash = (
            f"Synchronized provider={result['provider']} devices={result['devices_total']} "
            f"daily={result['daily_samples_total']} monthly={result['monthly_samples_total']} "
            f"snapshots={result['snapshots_total']} aggregated={result['aggregated_energy_updates']}"
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        flash = f"Sync failed: {exc}"
    return RedirectResponse(url=f"/?flash={quote_plus(flash)}", status_code=303)
