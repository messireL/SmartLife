from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BucketType, Device, EnergySample
from app.db.session import get_db
from app.services.dashboard_service import get_dashboard_summary
from app.services.sync_service import sync_from_provider

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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

    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {"request": request, "device": device, "daily": daily, "monthly": monthly},
    )


@router.post("/actions/sync-demo")
def sync_demo(db: Session = Depends(get_db)):
    result = sync_from_provider(db)
    flash = (
        f"Synchronized provider={result['provider']} devices={result['devices_total']} "
        f"daily={result['daily_samples_total']} monthly={result['monthly_samples_total']}"
    )
    return RedirectResponse(url=f"/?flash={flash}", status_code=303)
