from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import BucketType, Device, EnergySample, SyncRun, SyncRunStatus
from app.services.sync_runner import is_sync_running


ZERO = Decimal("0.000")



def get_dashboard_summary(db: Session) -> dict:
    today = date.today()
    month_start = today.replace(day=1)

    devices_total = db.scalar(select(func.count()).select_from(Device)) or 0
    online_total = db.scalar(select(func.count()).select_from(Device).where(Device.is_online.is_(True))) or 0
    powered_on_total = db.scalar(select(func.count()).select_from(Device).where(Device.switch_on.is_(True))) or 0

    day_total = db.scalar(
        select(func.coalesce(func.sum(EnergySample.energy_kwh), ZERO)).where(
            EnergySample.bucket_type == BucketType.DAY,
            EnergySample.period_start == today,
        )
    ) or ZERO

    month_total = db.scalar(
        select(func.coalesce(func.sum(EnergySample.energy_kwh), ZERO)).where(
            EnergySample.bucket_type == BucketType.MONTH,
            EnergySample.period_start == month_start,
        )
    ) or ZERO

    live_power_total = db.scalar(
        select(func.coalesce(func.sum(Device.current_power_w), Decimal("0.00"))).where(Device.current_power_w.is_not(None))
    ) or Decimal("0.00")

    return {
        "devices_total": devices_total,
        "online_total": online_total,
        "powered_on_total": powered_on_total,
        "day_total_kwh": day_total,
        "month_total_kwh": month_total,
        "live_power_total_w": live_power_total,
    }



def get_sync_overview(db: Session) -> dict:
    settings = get_settings()
    last_run = db.execute(select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(1)).scalar_one_or_none()
    success_total = db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.status == SyncRunStatus.SUCCESS)) or 0
    error_total = db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.status == SyncRunStatus.ERROR)) or 0
    return {
        "background_sync_enabled": settings.smartlife_background_sync_enabled,
        "sync_on_startup": settings.smartlife_sync_on_startup,
        "sync_interval_seconds": settings.smartlife_sync_interval_seconds,
        "is_running_now": is_sync_running(),
        "last_run": last_run,
        "success_total": success_total,
        "error_total": error_total,
    }
