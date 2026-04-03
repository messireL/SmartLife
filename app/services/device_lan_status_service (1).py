from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.db.models import Device
from app.integrations.base import ProviderDevice, ProviderStatusSnapshot
from app.integrations.tuya_provider import (
    TuyaCodeDefinition,
    TuyaDeviceSpec,
    _definition_from_serialized,
    _detect_device_profile,
    _normalize_mode,
    _parse_json_object,
    _scaled_decimal,
)
from app.services.device_lan_service import DeviceLanConfig, get_device_lan_configs_map
from app.services.tuya_local_service import TuyaLocalError, fetch_local_status, probe_local_device


@dataclass(slots=True)
class LocalStatusSyncOutcome:
    snapshots: list[ProviderStatusSnapshot]
    cloud_fallback_devices: list[ProviderDevice]
    local_candidates_total: int
    local_success_total: int
    local_failed_total: int
    local_failed_devices: list[str]


def collect_local_status_snapshots(
    db: Session,
    *,
    provider_devices: Sequence[ProviderDevice],
    device_map: dict[str, Device],
    cloud_allowed: bool,
) -> LocalStatusSyncOutcome:
    if not provider_devices:
        return LocalStatusSyncOutcome([], [], 0, 0, 0, [])

    device_ids = [device.id for device in device_map.values()]
    lan_map = get_device_lan_configs_map(db, device_ids)

    snapshots: list[ProviderStatusSnapshot] = []
    cloud_fallback_devices: list[ProviderDevice] = []
    local_failed_devices: list[str] = []
    local_candidates_total = 0

    for provider_device in provider_devices:
        device = device_map.get(provider_device.external_id)
        if device is None:
            if cloud_allowed:
                cloud_fallback_devices.append(provider_device)
            continue
        config = lan_map.get(device.id)
        if not _should_poll_locally(config):
            if cloud_allowed:
                cloud_fallback_devices.append(provider_device)
            continue

        local_candidates_total += 1
        try:
            snapshots.append(_build_local_snapshot(provider_device=provider_device, device=device, config=config))
        except TuyaLocalError:
            local_failed_devices.append(provider_device.external_id)
            if cloud_allowed:
                cloud_fallback_devices.append(provider_device)

    return LocalStatusSyncOutcome(
        snapshots=snapshots,
        cloud_fallback_devices=cloud_fallback_devices,
        local_candidates_total=local_candidates_total,
        local_success_total=len(snapshots),
        local_failed_total=len(local_failed_devices),
        local_failed_devices=local_failed_devices,
    )


def _should_poll_locally(config: DeviceLanConfig | None) -> bool:
    if config is None:
        return False
    return bool(config.local_enabled and config.is_complete and config.is_locally_verified)


def _looks_like_boiler_dps(dps: dict[str, Any]) -> bool:
    keys = {str(key) for key in dps.keys()}
    return {"1", "2", "9", "10"}.issubset(keys)


def _build_local_snapshot(*, provider_device: ProviderDevice, device: Device, config: DeviceLanConfig) -> ProviderStatusSnapshot:
    probe = fetch_local_status(
        device_id=provider_device.external_id,
        config=config,
        timeout_seconds=2,
    )
    spec = _spec_from_device(device)
    payload = probe.result if isinstance(probe.result, dict) else {}
    dps = payload.get("dps") if isinstance(payload.get("dps"), dict) else {}

    profile_hint = (device.device_profile or '').strip().lower() or None
    if _looks_like_boiler_dps(dps):
        profile_hint = 'boiler'

    metering_variant = None
    if profile_hint != 'boiler':
        if _looks_like_tdq_metering_plug(dps, spec):
            metering_variant = 'tdq'
        elif _looks_like_cz_metering_plug(dps, spec):
            metering_variant = 'cz'
        elif profile_hint in {'power_strip', 'metering_plug'}:
            metering_variant = 'cz'

    if metering_variant is not None:
        profile_hint = 'metering_plug'

    switch_on = _coalesce_bool(_first_value(payload, dps, ("switch", "switch_1"), ("1", 1)))

    if metering_variant == 'tdq':
        power_candidates = (("22", 1), (22, 1))
        voltage_candidates = (("23", 1), (23, 1))
        current_candidates = (("21", 0), (21, 0))
        energy_candidates = (("20", 3), (20, 3))
        fault_candidates = ("29", 29)
    else:
        power_candidates = (("19", 1), (19, 1), ("5", 1), (5, 1))
        voltage_candidates = (("20", 1), (20, 1), ("6", 1), (6, 1))
        current_candidates = (("18", 0), (18, 0), ("4", 0), (4, 0))
        energy_candidates = (("17", 3), (17, 3))
        fault_candidates = ("26", 26)

    power_w = _local_metric_decimal(payload, dps, code="cur_power", dps_candidates=power_candidates, definition=spec.definition("cur_power"))
    voltage_v = _local_metric_decimal(payload, dps, code="cur_voltage", dps_candidates=voltage_candidates, definition=spec.definition("cur_voltage"))
    current_raw = _local_metric_decimal(payload, dps, code="cur_current", dps_candidates=current_candidates, definition=spec.definition("cur_current"))
    current_a = None
    if current_raw is not None:
        current_a = (current_raw / Decimal("1000")).quantize(Decimal("0.001"))

    current_temperature_candidates: tuple[Any, ...] = ("3", 3, "101", 101)
    target_temperature_candidates: tuple[Any, ...] = ("2", 2, "102", 102)
    mode_candidates: tuple[Any, ...] = ("4", 4)

    if profile_hint == "boiler":
        current_temperature_candidates = ("10", 10, "3", 3, "101", 101)
        target_temperature_candidates = ("9", 9, "2", 2, "102", 102)
        mode_candidates = ("2", 2, "4", 4)

    current_temp_definition = None if profile_hint == 'boiler' else spec.definition('temp_current')
    target_temp_definition = None if profile_hint == 'boiler' else spec.definition('temp_set')
    current_temperature_c = _local_temperature_decimal(payload, dps, code="temp_current", dps_candidates=current_temperature_candidates, definition=current_temp_definition)
    target_temperature_c = _local_temperature_decimal(payload, dps, code="temp_set", dps_candidates=target_temperature_candidates, definition=target_temp_definition)
    operation_mode = _normalize_mode(_first_value(payload, dps, ("mode",), mode_candidates))
    energy_total_kwh = _local_metric_decimal(payload, dps, code="add_ele", dps_candidates=energy_candidates, definition=spec.definition("add_ele"))

    if profile_hint == "boiler":
        fault_raw = _first_value(payload, dps, ("fault",), ("20", 20))
    else:
        fault_raw = _first_value(payload, dps, ("fault",), fault_candidates + ("9", 9) if isinstance(fault_candidates, tuple) else ("26", 26, "9", 9))
    fault_code = None if fault_raw in (None, "", 0, "0") else str(fault_raw)

    profile = profile_hint or _detect_device_profile(provider_device, spec, current_temperature_c, target_temperature_c)
    telemetry_flags = {
        "switch": switch_on is not None,
        "power": power_w is not None,
        "voltage": voltage_v is not None,
        "current": current_a is not None,
        "energy_total": energy_total_kwh is not None,
        "current_temperature": current_temperature_c is not None,
        "target_temperature": target_temperature_c is not None,
        "mode": operation_mode is not None,
        "fault": fault_code not in (None, "0"),
    }
    raw_payload = json.dumps(
        {
            "transport": "tuya_local",
            "probe_result": payload,
            "ip": probe.ip,
            "version": probe.protocol_version,
            "telemetry_flags": telemetry_flags,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )

    telemetry_present = any(telemetry_flags[key] for key in ("power", "voltage", "current", "energy_total", "current_temperature", "target_temperature"))
    source_note = f"tuya local status · {probe.ip} · v{probe.protocol_version}"
    if not telemetry_present:
        source_note += " · status-only"

    return ProviderStatusSnapshot(
        external_id=provider_device.external_id,
        recorded_at=datetime.utcnow().replace(microsecond=0),
        switch_on=switch_on,
        power_w=power_w,
        voltage_v=voltage_v,
        current_a=current_a,
        energy_total_kwh=energy_total_kwh,
        fault_code=fault_code or "0",
        current_temperature_c=current_temperature_c,
        target_temperature_c=target_temperature_c,
        operation_mode=operation_mode,
        device_profile=profile,
        control_codes=tuple(device.control_codes),
        available_modes=tuple(device.available_modes),
        target_temperature_min_c=device.target_temperature_min_c,
        target_temperature_max_c=device.target_temperature_max_c,
        target_temperature_step_c=device.target_temperature_step_c,
        source_note=source_note,
        raw_payload=raw_payload,
    )


def _looks_like_cz_metering_plug(dps: dict[str, Any], spec: TuyaDeviceSpec) -> bool:
    if {'17', '18', '19', '20'}.issubset({str(key) for key in dps.keys()}):
        return True
    return all(code in spec.all_codes for code in ('add_ele', 'cur_current', 'cur_power', 'cur_voltage'))


def _looks_like_tdq_metering_plug(dps: dict[str, Any], spec: TuyaDeviceSpec) -> bool:
    keys = {str(key) for key in dps.keys()}
    if {'20', '21', '22', '23'}.issubset(keys):
        return True
    return all(code in spec.all_codes for code in ('add_ele', 'cur_current', 'cur_power', 'cur_voltage')) and '29' in keys


def _looks_like_metering_plug(payload: dict[str, Any], dps: dict[str, Any], spec: TuyaDeviceSpec) -> bool:
    return _looks_like_cz_metering_plug(dps, spec) or _looks_like_tdq_metering_plug(dps, spec)


def _spec_from_device(device: Device) -> TuyaDeviceSpec:
    payload = _parse_json_object(device.last_status_payload)
    status_definitions_raw = payload.get("status_definitions") if isinstance(payload.get("status_definitions"), dict) else {}
    function_definitions_raw = payload.get("function_definitions") if isinstance(payload.get("function_definitions"), dict) else {}

    status_map = {
        str(code): _definition_from_serialized(raw)
        for code, raw in status_definitions_raw.items()
        if isinstance(raw, dict)
    }
    function_map = {
        str(code): _definition_from_serialized(raw)
        for code, raw in function_definitions_raw.items()
        if isinstance(raw, dict)
    }

    # Minimal fallbacks for LAN-only devices that never stored cloud definitions.
    for code, scale in (("cur_power", 1), ("cur_voltage", 1), ("cur_current", 0), ("add_ele", 3), ("temp_current", 1), ("temp_set", 1)):
        if code not in status_map:
            status_map[code] = TuyaCodeDefinition(code=code, scale=scale)
    if "mode" not in function_map:
        function_map["mode"] = TuyaCodeDefinition(code="mode", scale=0)

    return TuyaDeviceSpec(status_map=status_map, function_map=function_map)


def _first_value(payload: dict[str, Any], dps: dict[str, Any], code_candidates: Sequence[str], dps_candidates: Sequence[Any]) -> Any:
    for code in code_candidates:
        if code in payload:
            value = payload.get(code)
            if value not in (None, ""):
                return value
    for key in dps_candidates:
        if key in dps:
            value = dps.get(key)
            if value not in (None, ""):
                return value
        key_text = str(key)
        if key_text in dps:
            value = dps.get(key_text)
            if value not in (None, ""):
                return value
    return None


def _coalesce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "on", "1", "yes"}:
        return True
    if text in {"false", "off", "0", "no"}:
        return False
    return None


def _local_metric_decimal(
    payload: dict[str, Any],
    dps: dict[str, Any],
    *,
    code: str,
    dps_candidates: Sequence[tuple[Any, int]],
    definition: TuyaCodeDefinition | None,
) -> Decimal | None:
    if code in payload:
        return _scaled_decimal(payload.get(code), definition)
    for key, fallback_scale in dps_candidates:
        value = dps.get(key)
        if value in (None, ""):
            value = dps.get(str(key))
        if value in (None, ""):
            continue
        fallback_definition = definition or TuyaCodeDefinition(code=code, scale=fallback_scale)
        return _scaled_decimal(value, fallback_definition)
    return None


def _local_temperature_decimal(
    payload: dict[str, Any],
    dps: dict[str, Any],
    *,
    code: str,
    dps_candidates: Sequence[Any],
    definition: TuyaCodeDefinition | None,
) -> Decimal | None:
    if code in payload:
        return _scaled_decimal(payload.get(code), definition)
    for key in dps_candidates:
        value = dps.get(key)
        if value in (None, ""):
            value = dps.get(str(key))
        if value in (None, ""):
            continue
        fallback = definition
        if fallback is None:
            scale = 1 if str(value).isdigit() and abs(int(value)) >= 100 else 0
            fallback = TuyaCodeDefinition(code=code, scale=scale)
        return _scaled_decimal(value, fallback)
    return None
