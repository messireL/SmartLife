from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BucketType, Device, EnergySample
from app.integrations.base import ProviderDevice, ProviderEnergySample
from app.integrations.registry import get_provider


def sync_from_provider(db: Session) -> dict:
    provider = get_provider()
    devices = provider.get_devices()
    daily_samples = provider.get_daily_energy_samples()
    monthly_samples = provider.get_monthly_energy_samples()

    device_map = _upsert_devices(db, devices)
    inserted_daily = _upsert_energy_samples(db, BucketType.DAY, daily_samples, device_map)
    inserted_monthly = _upsert_energy_samples(db, BucketType.MONTH, monthly_samples, device_map)
    db.commit()

    return {
        "provider": provider.provider_name.value,
        "devices_total": len(devices),
        "daily_samples_total": inserted_daily,
        "monthly_samples_total": inserted_monthly,
    }


def _upsert_devices(db: Session, devices: Iterable[ProviderDevice]) -> dict[str, Device]:
    device_map: dict[str, Device] = {}
    for item in devices:
        device = db.execute(
            select(Device).where(Device.provider == item.provider, Device.external_id == item.external_id)
        ).scalar_one_or_none()
        if device is None:
            device = Device(provider=item.provider, external_id=item.external_id)
            db.add(device)
        device.name = item.name
        device.model = item.model
        device.category = item.category
        device.room_name = item.room_name
        device.location_name = item.location_name
        device.is_online = item.is_online
        device.last_seen_at = item.last_seen_at
        device.notes = item.notes
        db.flush()
        device_map[item.external_id] = device
    return device_map


def _upsert_energy_samples(
    db: Session,
    bucket_type: BucketType,
    samples: Iterable[ProviderEnergySample],
    device_map: dict[str, Device],
) -> int:
    upserted = 0
    for item in samples:
        device = device_map.get(item.external_id)
        if device is None:
            continue
        sample = db.execute(
            select(EnergySample).where(
                EnergySample.device_id == device.id,
                EnergySample.bucket_type == bucket_type,
                EnergySample.period_start == item.period_start,
            )
        ).scalar_one_or_none()
        if sample is None:
            sample = EnergySample(device_id=device.id, bucket_type=bucket_type, period_start=item.period_start)
            db.add(sample)
        sample.energy_kwh = item.energy_kwh
        sample.power_w = item.power_w
        sample.voltage_v = item.voltage_v
        sample.current_a = item.current_a
        sample.source_note = item.source_note
        upserted += 1
    return upserted
