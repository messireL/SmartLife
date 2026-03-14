from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BucketType, Device, EnergySample


def get_dashboard_summary(db: Session) -> dict:
    today = date.today()
    month_start = today.replace(day=1)

    devices_total = db.scalar(select(func.count()).select_from(Device)) or 0
    online_total = db.scalar(select(func.count()).select_from(Device).where(Device.is_online.is_(True))) or 0

    day_total = db.scalar(
        select(func.coalesce(func.sum(EnergySample.energy_kwh), Decimal("0.000"))).where(
            EnergySample.bucket_type == BucketType.DAY,
            EnergySample.period_start == today,
        )
    ) or Decimal("0.000")

    month_total = db.scalar(
        select(func.coalesce(func.sum(EnergySample.energy_kwh), Decimal("0.000"))).where(
            EnergySample.bucket_type == BucketType.MONTH,
            EnergySample.period_start == month_start,
        )
    ) or Decimal("0.000")

    return {
        "devices_total": devices_total,
        "online_total": online_total,
        "day_total_kwh": day_total,
        "month_total_kwh": month_total,
    }
