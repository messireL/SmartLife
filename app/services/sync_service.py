from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.timeutils import local_day_start_from_utc, local_month_start_from_utc
from app.db.models import BucketType, Device, DeviceStatusSnapshot, EnergySample, ProviderType, SyncRunTrigger
from app.integrations.base import ProviderDevice, ProviderEnergySample, ProviderStatusSnapshot
from app.integrations.registry import get_provider
from app.integrations.tuya_provider import TuyaCloudProvider
from app.services.runtime_config_service import TUYA_API_MODE_MANUAL, mark_tuya_full_sync_completed
from app.services.device_lan_status_service import collect_local_status_snapshots
from app.services.device_query_service import is_temp_device_name

from sqlalchemy import func

ZERO = Decimal("0.000")


def sync_from_provider(db: Session, *, trigger: SyncRunTrigger = SyncRunTrigger.MANUAL) -> dict:
    provider = get_provider(db)
    sync_mode = "full"
    sync_reason = "provider default"
    refresh_devices_from_cloud = True
    use_cached_spec = False

    if isinstance(provider, TuyaCloudProvider):
        if provider.runtime.tuya_api_mode == TUYA_API_MODE_MANUAL:
            sync_mode = "local_only"
            sync_reason = f"manual cloud mode blocks cloud sync for {trigger.value}, local LAN status only"
            refresh_devices_from_cloud = False
            use_cached_spec = True
        elif trigger in {SyncRunTrigger.MANUAL, SyncRunTrigger.CLI, SyncRunTrigger.STARTUP}:
            sync_mode = "full"
            sync_reason = f"{trigger.value} trigger forces full sync"
        else:
            plan = provider.plan_sync()
            sync_mode = plan.mode
            sync_reason = plan.reason
            refresh_devices_from_cloud = plan.refresh_devices_from_cloud
            use_cached_spec = plan.use_cached_spec

    devices = provider.get_devices() if refresh_devices_from_cloud else provider.get_cached_devices()
    daily_samples = provider.get_daily_energy_samples() if refresh_devices_from_cloud else []
    monthly_samples = provider.get_monthly_energy_samples() if refresh_devices_from_cloud else []

    pruned_devices = _prune_missing_provider_devices(db, provider.provider_name, devices) if refresh_devices_from_cloud else 0
    device_map = _upsert_devices(db, devices)

    local_sync = collect_local_status_snapshots(
        db,
        provider_devices=devices,
        device_map=device_map,
        cloud_allowed=not (isinstance(provider, TuyaCloudProvider) and sync_mode == "local_only"),
    ) if provider.provider_name == ProviderType.TUYA_CLOUD else None

    if isinstance(provider, TuyaCloudProvider):
        cloud_snapshot_devices = local_sync.cloud_fallback_devices if local_sync is not None else list(devices)
        cloud_snapshots = provider.get_status_snapshots(cloud_snapshot_devices, use_cached_spec=use_cached_spec) if cloud_snapshot_devices else []
    else:
        cloud_snapshots = provider.get_status_snapshots(devices)

    snapshots = list(cloud_snapshots)
    if local_sync is not None:
        snapshots.extend(local_sync.snapshots)

    inserted_daily = _upsert_energy_samples(db, BucketType.DAY, daily_samples, device_map)
    inserted_monthly = _upsert_energy_samples(db, BucketType.MONTH, monthly_samples, device_map)
    aggregate_from_snapshots = len(daily_samples) == 0 and len(monthly_samples) == 0
    inserted_snapshots, aggregated_deltas = _store_status_snapshots(
        db,
        snapshots,
        device_map,
        aggregate_energy=aggregate_from_snapshots,
    )
    if isinstance(provider, TuyaCloudProvider) and sync_mode == "full":
        mark_tuya_full_sync_completed(db)
    db.commit()

    return {
        "provider": provider.provider_name.value,
        "sync_mode": sync_mode,
        "sync_reason": sync_reason,
        "refreshed_devices_from_cloud": refresh_devices_from_cloud,
        "used_cached_spec": use_cached_spec,
        "devices_total": len(devices),
        "daily_samples_total": inserted_daily,
        "monthly_samples_total": inserted_monthly,
        "snapshots_total": inserted_snapshots,
        "cloud_snapshots_total": len(cloud_snapshots),
        "local_snapshots_total": local_sync.local_success_total if local_sync is not None else 0,
        "local_candidates_total": local_sync.local_candidates_total if local_sync is not None else 0,
        "local_failed_total": local_sync.local_failed_total if local_sync is not None else 0,
        "aggregated_energy_updates": aggregated_deltas,
        "pruned_devices_total": pruned_devices,
    }



def _prune_missing_provider_devices(db: Session, provider: ProviderType, devices: Sequence[ProviderDevice]) -> int:
    current_ids = {item.external_id for item in devices}
    existing = db.execute(select(Device).where(Device.provider == provider, Device.is_deleted.is_(False))).scalars().all()
    stale_ids = [row.id for row in existing if row.external_id not in current_ids]
    if not stale_ids:
        return 0
    db.execute(delete(Device).where(Device.id.in_(stale_ids)))
    return len(stale_ids)



def _upsert_devices(db: Session, devices: Iterable[ProviderDevice]) -> dict[str, Device]:
    device_map: dict[str, Device] = {}
    for item in devices:
        device = db.execute(
            select(Device).where(Device.provider == item.provider, Device.external_id == item.external_id)
        ).scalar_one_or_none()
        if device is not None and device.is_deleted:
            if item.provider == ProviderType.DEMO:
                continue
            device.is_deleted = False
            device.deleted_reason = None
            device.deleted_at = None
            if device.hidden_reason == "deleted by user":
                device.is_hidden = False
                device.hidden_reason = None
        if device is None:
            device = Device(provider=item.provider, external_id=item.external_id)
            db.add(device)
        device.name = item.name
        device.model = item.model
        device.product_id = item.product_id
        device.product_name = item.product_name
        device.category = item.category
        device.room_name = item.room_name
        device.location_name = item.location_name
        device.icon_url = item.icon_url
        device.is_online = item.is_online
        device.last_seen_at = item.last_seen_at
        device.notes = item.notes
        if _should_auto_hide_temp_device(item.name) and device.hidden_reason != "shown by user":
            device.is_hidden = True
            device.hidden_reason = "auto-hidden temp device"
        db.flush()
        device_map[item.external_id] = device
    return device_map



def _upsert_energy_samples(
    db: Session,
    bucket_type: BucketType,
    samples: Sequence[ProviderEnergySample],
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



def _store_status_snapshots(
    db: Session,
    snapshots: Sequence[ProviderStatusSnapshot],
    device_map: dict[str, Device],
    *,
    aggregate_energy: bool,
) -> tuple[int, int]:
    inserted = 0
    aggregated = 0

    for item in snapshots:
        device = device_map.get(item.external_id)
        if device is None:
            continue

        previous = db.execute(
            select(DeviceStatusSnapshot)
            .where(DeviceStatusSnapshot.device_id == device.id)
            .order_by(DeviceStatusSnapshot.recorded_at.desc(), DeviceStatusSnapshot.id.desc())
            .limit(1)
        ).scalar_one_or_none()

        effective_power_w = item.power_w
        effective_voltage_v = item.voltage_v
        effective_current_a = item.current_a
        telemetry_backfilled = False

        if effective_power_w is None:
            effective_power_w = _latest_non_null_metric(device.current_power_w, previous.power_w if previous is not None else None)
            telemetry_backfilled = telemetry_backfilled or effective_power_w is not None
        if effective_voltage_v is None:
            effective_voltage_v = _latest_non_null_metric(device.current_voltage_v, previous.voltage_v if previous is not None else None)
            telemetry_backfilled = telemetry_backfilled or effective_voltage_v is not None
        if effective_current_a is None:
            effective_current_a = _latest_non_null_metric(device.current_a, previous.current_a if previous is not None else None)
            telemetry_backfilled = telemetry_backfilled or effective_current_a is not None

        source_note = item.source_note
        if telemetry_backfilled:
            source_note = f"{source_note} · keep last electrical metrics" if source_note else "keep last electrical metrics"

        snapshot = DeviceStatusSnapshot(
            device_id=device.id,
            recorded_at=item.recorded_at,
            switch_on=item.switch_on,
            power_w=effective_power_w,
            voltage_v=effective_voltage_v,
            current_a=effective_current_a,
            energy_total_kwh=item.energy_total_kwh,
            fault_code=item.fault_code,
            current_temperature_c=item.current_temperature_c,
            target_temperature_c=item.target_temperature_c,
            operation_mode=item.operation_mode,
            source_note=source_note,
            raw_payload=item.raw_payload,
        )
        db.add(snapshot)

        device.switch_on = item.switch_on
        device.current_power_w = effective_power_w
        device.current_voltage_v = effective_voltage_v
        device.current_a = effective_current_a
        device.energy_total_kwh = item.energy_total_kwh
        device.fault_code = item.fault_code
        device.device_profile = item.device_profile
        device.current_temperature_c = item.current_temperature_c
        device.target_temperature_c = item.target_temperature_c
        device.operation_mode = item.operation_mode
        device.control_codes_json = json.dumps(list(item.control_codes), ensure_ascii=False) if item.control_codes else None
        device.available_modes_json = json.dumps(list(item.available_modes), ensure_ascii=False) if item.available_modes else None
        device.target_temperature_min_c = item.target_temperature_min_c
        device.target_temperature_max_c = item.target_temperature_max_c
        device.target_temperature_step_c = item.target_temperature_step_c
        device.last_status_at = item.recorded_at
        device.last_status_payload = item.raw_payload
        device.is_online = True
        if item.recorded_at:
            device.last_seen_at = item.recorded_at

        inserted += 1

        if not aggregate_energy:
            continue
        if item.energy_total_kwh is None or previous is None or previous.energy_total_kwh is None:
            continue

        delta = (item.energy_total_kwh - previous.energy_total_kwh).quantize(Decimal("0.001"))
        if delta <= ZERO:
            continue

        _increment_aggregate(
            db,
            device=device,
            bucket_type=BucketType.DAY,
            period_start=local_day_start_from_utc(item.recorded_at),
            delta_kwh=delta,
            power_w=effective_power_w,
            voltage_v=effective_voltage_v,
            current_a=effective_current_a,
            source_note=source_note or "live energy delta",
        )
        _increment_aggregate(
            db,
            device=device,
            bucket_type=BucketType.MONTH,
            period_start=local_month_start_from_utc(item.recorded_at),
            delta_kwh=delta,
            power_w=effective_power_w,
            voltage_v=effective_voltage_v,
            current_a=effective_current_a,
            source_note=source_note or "live energy delta",
        )
        aggregated += 2

    return inserted, aggregated



def _latest_non_null_metric(current_value: Decimal | None, previous_value: Decimal | None) -> Decimal | None:
    if current_value is not None:
        return current_value
    return previous_value



def _increment_aggregate(
    db: Session,
    *,
    device: Device,
    bucket_type: BucketType,
    period_start: date,
    delta_kwh: Decimal,
    power_w: Decimal | None,
    voltage_v: Decimal | None,
    current_a: Decimal | None,
    source_note: str,
) -> None:
    sample = db.execute(
        select(EnergySample).where(
            EnergySample.device_id == device.id,
            EnergySample.bucket_type == bucket_type,
            EnergySample.period_start == period_start,
        )
    ).scalar_one_or_none()
    if sample is None:
        sample = EnergySample(
            device_id=device.id,
            bucket_type=bucket_type,
            period_start=period_start,
            energy_kwh=ZERO,
        )
        db.add(sample)

    sample.energy_kwh = (Decimal(sample.energy_kwh or ZERO) + delta_kwh).quantize(Decimal("0.001"))
    sample.power_w = power_w
    sample.voltage_v = voltage_v
    sample.current_a = current_a
    sample.source_note = source_note


def _should_auto_hide_temp_device(name: str | None) -> bool:
    return is_temp_device_name(name)
