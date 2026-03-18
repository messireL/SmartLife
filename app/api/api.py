from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.version import APP_VERSION
from app.db.models import BucketType, Device, DeviceCommandLog, DeviceStatusSnapshot, EnergySample, SyncRun
from app.db.session import get_db
from app.services.dashboard_service import get_dashboard_summary, get_sync_overview
from app.services.runtime_config_service import get_runtime_config
from app.services.runtime_diagnostics_service import get_runtime_diagnostics

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/devices")
def list_devices(include_hidden: bool = Query(default=False), db: Session = Depends(get_db)):
    stmt = select(Device).where(Device.is_deleted.is_(False))
    if not include_hidden:
        stmt = stmt.where(Device.is_hidden.is_(False))
    devices = db.execute(stmt.order_by(Device.custom_room_name, Device.room_name, Device.custom_name, Device.name)).scalars().all()
    return [
        {
            "id": device.id,
            "external_id": device.external_id,
            "provider": device.provider.value,
            "name": device.name,
            "display_name": device.display_name,
            "model": device.model,
            "product_id": device.product_id,
            "product_name": device.product_name,
            "category": device.category,
            "room_name": device.room_name,
            "display_room_name": device.display_room_name,
            "location_name": device.location_name,
            "icon_url": device.icon_url,
            "is_online": device.is_online,
            "is_hidden": device.is_hidden,
            "hidden_reason": device.hidden_reason,
            "switch_on": device.switch_on,
            "current_power_w": float(device.current_power_w) if device.current_power_w is not None else None,
            "current_voltage_v": float(device.current_voltage_v) if device.current_voltage_v is not None else None,
            "current_a": float(device.current_a) if device.current_a is not None else None,
            "energy_total_kwh": float(device.energy_total_kwh) if device.energy_total_kwh is not None else None,
            "fault_code": device.fault_code,
            "device_profile": device.device_profile,
            "current_temperature_c": float(device.current_temperature_c) if device.current_temperature_c is not None else None,
            "target_temperature_c": float(device.target_temperature_c) if device.target_temperature_c is not None else None,
            "operation_mode": device.operation_mode,
            "control_codes": device.control_codes,
            "available_modes": device.available_modes,
            "target_temperature_min_c": float(device.target_temperature_min_c) if device.target_temperature_min_c is not None else None,
            "target_temperature_max_c": float(device.target_temperature_max_c) if device.target_temperature_max_c is not None else None,
            "target_temperature_step_c": float(device.target_temperature_step_c) if device.target_temperature_step_c is not None else None,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "last_status_at": device.last_status_at.isoformat() if device.last_status_at else None,
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
    if device is None or device.is_deleted:
        raise HTTPException(status_code=404, detail="device not found")

    samples = db.execute(
        select(EnergySample)
        .where(EnergySample.device_id == device.id, EnergySample.bucket_type == bucket)
        .order_by(EnergySample.period_start.desc())
        .limit(100)
    ).scalars().all()

    return {
        "device": {
            "id": device.id,
            "name": device.name,
            "display_name": device.display_name,
            "provider": device.provider.value,
            "current_power_w": float(device.current_power_w) if device.current_power_w is not None else None,
            "energy_total_kwh": float(device.energy_total_kwh) if device.energy_total_kwh is not None else None,
        },
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


@router.get("/devices/{device_id}/snapshots")
def device_snapshots(device_id: int, limit: int = 100, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None or device.is_deleted:
        raise HTTPException(status_code=404, detail="device not found")

    limit = max(1, min(limit, 500))
    items = db.execute(
        select(DeviceStatusSnapshot)
        .where(DeviceStatusSnapshot.device_id == device.id)
        .order_by(DeviceStatusSnapshot.recorded_at.desc(), DeviceStatusSnapshot.id.desc())
        .limit(limit)
    ).scalars().all()

    return {
        "device": {"id": device.id, "name": device.name,
            "display_name": device.display_name, "provider": device.provider.value},
        "items": [
            {
                "recorded_at": item.recorded_at.isoformat(),
                "switch_on": item.switch_on,
                "power_w": float(item.power_w) if item.power_w is not None else None,
                "voltage_v": float(item.voltage_v) if item.voltage_v is not None else None,
                "current_a": float(item.current_a) if item.current_a is not None else None,
                "energy_total_kwh": float(item.energy_total_kwh) if item.energy_total_kwh is not None else None,
                "fault_code": item.fault_code,
                "current_temperature_c": float(item.current_temperature_c) if item.current_temperature_c is not None else None,
                "target_temperature_c": float(item.target_temperature_c) if item.target_temperature_c is not None else None,
                "operation_mode": item.operation_mode,
                "source_note": item.source_note,
            }
            for item in items
        ],
    }


@router.get("/devices/{device_id}/commands")
def device_commands(device_id: int, limit: int = 20, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None or device.is_deleted:
        raise HTTPException(status_code=404, detail="device not found")
    limit = max(1, min(limit, 100))
    items = db.execute(
        select(DeviceCommandLog)
        .where(DeviceCommandLog.device_id == device.id)
        .order_by(DeviceCommandLog.requested_at.desc(), DeviceCommandLog.id.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": item.id,
            "command_code": item.command_code,
            "command_value": item.command_value,
            "status": item.status.value,
            "provider": item.provider,
            "requested_at": item.requested_at.isoformat() if item.requested_at else None,
            "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            "result_summary": item.result_summary,
            "error_message": item.error_message,
        }
        for item in items
    ]




@router.get("/runtime/diagnostics")
def runtime_diagnostics(db: Session = Depends(get_db)):
    diagnostics = get_runtime_diagnostics(db)
    return diagnostics.to_dict()


@router.get("/sync/status")
def sync_status(db: Session = Depends(get_db)):
    overview = get_sync_overview(db)
    summary = get_dashboard_summary(db)
    last_run = overview["last_run"]
    return {
        "background_sync_enabled": overview["background_sync_enabled"],
        "sync_on_startup": overview["sync_on_startup"],
        "sync_interval_seconds": overview["sync_interval_seconds"],
        "tuya_api_mode": overview["tuya_api_mode"],
        "tuya_api_mode_label": overview["tuya_api_mode_label"],
        "tuya_full_sync_interval_minutes": overview["tuya_full_sync_interval_minutes"],
        "tuya_spec_cache_hours": overview["tuya_spec_cache_hours"],
        "tuya_last_full_sync_at": overview["tuya_last_full_sync_at"],
        "is_running_now": overview["is_running_now"],
        "success_total": overview["success_total"],
        "error_total": overview["error_total"],
        "last_run": {
            "id": last_run.id,
            "provider": last_run.provider,
            "trigger": last_run.trigger.value,
            "status": last_run.status.value,
            "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
            "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
            "duration_ms": last_run.duration_ms,
            "result_summary": last_run.result_summary,
            "error_message": last_run.error_message,
        }
        if last_run
        else None,
    }


@router.get("/sync/runs")
def sync_runs(limit: int = 20, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    items = db.execute(select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(limit)).scalars().all()
    return [
        {
            "id": item.id,
            "provider": item.provider,
            "trigger": item.trigger.value,
            "status": item.status.value,
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            "duration_ms": item.duration_ms,
            "result_summary": item.result_summary,
            "error_message": item.error_message,
        }
        for item in items
    ]


@router.get("/health")
def health(db: Session = Depends(get_db)):
    settings = get_settings()
    runtime = get_runtime_config(db)
    overview = get_sync_overview(db)
    summary = get_dashboard_summary(db)
    last_run = overview["last_run"]
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": APP_VERSION,
        "provider": runtime.provider,
        "base_url": settings.app_base_url,
        "timezone": settings.timezone,
        "sync_interval_seconds": settings.smartlife_sync_interval_seconds,
        "background_sync_enabled": settings.smartlife_background_sync_enabled,
        "tuya_api_mode": runtime.tuya_api_mode,
        "tuya_api_mode_label": runtime.tuya_api_mode_label,
        "tuya_full_sync_interval_minutes": runtime.tuya_full_sync_interval_minutes,
        "tuya_spec_cache_hours": runtime.tuya_spec_cache_hours,
        "tuya_last_full_sync_at": runtime.tuya_last_full_sync_at or None,
        "sync_on_startup": settings.smartlife_sync_on_startup,
        "sync_running_now": overview["is_running_now"],
        "last_sync_status": last_run.status.value if last_run else None,
        "last_sync_started_at": last_run.started_at.isoformat() if last_run and last_run.started_at else None,
        "tariff_price_per_kwh": float(summary["tariff_price_per_kwh"]),
        "tariff_currency": summary["tariff_currency"],
        "tariff_mode": summary["tariff_mode"],
        "tariff_mode_label": summary["tariff_mode_label"],
        "tariff_display": summary["tariff_display"],
    }
