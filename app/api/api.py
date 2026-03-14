from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import BucketType, Device, EnergySample
from app.db.session import get_db

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    devices = db.execute(select(Device).order_by(Device.room_name, Device.name)).scalars().all()
    return [
        {
            "id": device.id,
            "external_id": device.external_id,
            "provider": device.provider.value,
            "name": device.name,
            "model": device.model,
            "category": device.category,
            "room_name": device.room_name,
            "location_name": device.location_name,
            "is_online": device.is_online,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "notes": device.notes,
        }
        for device in devices
    ]


@router.get("/devices/{device_id}/energy")
def device_energy(device_id: int, period: str = "day", db: Session = Depends(get_db)):
    bucket = BucketType.DAY if period == "day" else BucketType.MONTH if period == "month" else None
    if bucket is None:
        raise HTTPException(status_code=400, detail="period must be 'day' or 'month'")

    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    samples = db.execute(
        select(EnergySample)
        .where(EnergySample.device_id == device.id, EnergySample.bucket_type == bucket)
        .order_by(EnergySample.period_start.desc())
        .limit(100)
    ).scalars().all()

    return {
        "device": {"id": device.id, "name": device.name, "provider": device.provider.value},
        "period": bucket.value,
        "items": [
            {
                "period_start": sample.period_start.isoformat(),
                "energy_kwh": float(sample.energy_kwh),
                "power_w": float(sample.power_w) if sample.power_w is not None else None,
                "voltage_v": float(sample.voltage_v) if sample.voltage_v is not None else None,
                "current_a": float(sample.current_a) if sample.current_a is not None else None,
                "source_note": sample.source_note,
            }
            for sample in samples
        ],
    }


@router.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "provider": settings.smartlife_provider,
        "base_url": settings.app_base_url,
        "timezone": settings.timezone,
    }
