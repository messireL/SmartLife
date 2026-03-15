from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.timeutils import local_day_start_from_utc, local_month_start_from_utc
from app.db.models import BucketType, Device, DeviceStatusSnapshot, EnergySample

ZERO = Decimal('0.000')


def rebuild_energy_aggregates_from_snapshots(db: Session) -> dict:
    devices = db.execute(select(Device).order_by(Device.id)).scalars().all()
    device_ids = [device.id for device in devices]

    deleted_samples = 0
    if device_ids:
        deleted_samples = db.execute(
            delete(EnergySample).where(EnergySample.device_id.in_(device_ids))
        ).rowcount or 0

    rebuilt_daily = 0
    rebuilt_monthly = 0
    updated_devices = 0

    for device in devices:
        snapshots = db.execute(
            select(DeviceStatusSnapshot)
            .where(DeviceStatusSnapshot.device_id == device.id)
            .order_by(DeviceStatusSnapshot.recorded_at.asc(), DeviceStatusSnapshot.id.asc())
        ).scalars().all()

        if not snapshots:
            continue

        updated_devices += 1
        previous = None
        daily_buckets: dict = defaultdict(lambda: ZERO)
        monthly_buckets: dict = defaultdict(lambda: ZERO)
        latest_power = None
        latest_voltage = None
        latest_current = None
        latest_source = None

        for snapshot in snapshots:
            if previous is not None and previous.energy_total_kwh is not None and snapshot.energy_total_kwh is not None:
                delta = (Decimal(snapshot.energy_total_kwh) - Decimal(previous.energy_total_kwh)).quantize(Decimal('0.001'))
                if delta > ZERO:
                    day_key = local_day_start_from_utc(snapshot.recorded_at)
                    month_key = local_month_start_from_utc(snapshot.recorded_at)
                    daily_buckets[day_key] = (daily_buckets[day_key] + delta).quantize(Decimal('0.001'))
                    monthly_buckets[month_key] = (monthly_buckets[month_key] + delta).quantize(Decimal('0.001'))
                    latest_power = snapshot.power_w
                    latest_voltage = snapshot.voltage_v
                    latest_current = snapshot.current_a
                    latest_source = snapshot.source_note or 'rebuild from snapshots'
            previous = snapshot

        for period_start, energy_kwh in sorted(daily_buckets.items()):
            db.add(EnergySample(
                device_id=device.id,
                bucket_type=BucketType.DAY,
                period_start=period_start,
                energy_kwh=energy_kwh,
                power_w=latest_power,
                voltage_v=latest_voltage,
                current_a=latest_current,
                source_note=latest_source or 'rebuild from snapshots',
            ))
            rebuilt_daily += 1

        for period_start, energy_kwh in sorted(monthly_buckets.items()):
            db.add(EnergySample(
                device_id=device.id,
                bucket_type=BucketType.MONTH,
                period_start=period_start,
                energy_kwh=energy_kwh,
                power_w=latest_power,
                voltage_v=latest_voltage,
                current_a=latest_current,
                source_note=latest_source or 'rebuild from snapshots',
            ))
            rebuilt_monthly += 1

    db.commit()
    return {
        'devices_total': len(devices),
        'devices_with_snapshots': updated_devices,
        'deleted_samples': deleted_samples,
        'rebuilt_daily_samples': rebuilt_daily,
        'rebuilt_monthly_samples': rebuilt_monthly,
    }
