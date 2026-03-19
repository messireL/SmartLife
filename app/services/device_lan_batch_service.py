from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Device, ProviderType
from app.services.device_lan_key_service import DeviceLanKeyError, reprobe_device_lan_profile
from app.services.device_lan_service import get_device_lan_config, record_device_lan_fetch, save_device_lan_config


@dataclass(slots=True)
class DeviceLanInventoryOverview:
    total_devices: int = 0
    configured_total: int = 0
    enabled_total: int = 0
    complete_total: int = 0
    prefer_local_total: int = 0
    with_key_total: int = 0
    probe_success_total: int = 0
    probe_error_total: int = 0


@dataclass(slots=True)
class DeviceLanImportResult:
    filename: str
    rows_total: int = 0
    matched_total: int = 0
    changed_total: int = 0
    unchanged_total: int = 0
    skipped_total: int = 0
    unmatched_total: int = 0
    key_updates_total: int = 0
    errors: list[str] = field(default_factory=list)
    unmatched_external_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeviceLanBatchProbeItem:
    device_id: int
    display_name: str
    local_ip: str
    protocol_version: str
    status: str
    message: str


@dataclass(slots=True)
class DeviceLanBatchProbeResult:
    scope: str
    candidates_total: int = 0
    success_total: int = 0
    error_total: int = 0
    skipped_total: int = 0
    items: list[DeviceLanBatchProbeItem] = field(default_factory=list)


_ALLOWED_IMPORT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")


def get_device_lan_inventory_overview(db: Session) -> DeviceLanInventoryOverview:
    devices = db.execute(
        select(Device).where(Device.is_deleted.is_(False)).order_by(Device.id.asc())
    ).scalars().all()
    overview = DeviceLanInventoryOverview(total_devices=len(devices))
    for device in devices:
        config = get_device_lan_config(db, device.id)
        if config.local_ip or config.local_key or config.local_enabled or config.prefer_local:
            overview.configured_total += 1
        if config.local_enabled:
            overview.enabled_total += 1
        if config.is_complete:
            overview.complete_total += 1
        if config.prefer_local:
            overview.prefer_local_total += 1
        if config.has_local_key:
            overview.with_key_total += 1
        status = (config.last_probe_status or "").strip().lower()
        if status == "success":
            overview.probe_success_total += 1
        elif status == "error":
            overview.probe_error_total += 1
    return overview


def import_device_lan_csv(db: Session, *, filename: str, content: bytes) -> DeviceLanImportResult:
    result = DeviceLanImportResult(filename=filename or "devices-lan-import.csv")
    text = _decode_csv_bytes(content)
    reader = csv.DictReader(io.StringIO(text), dialect=_detect_dialect(text))
    if not reader.fieldnames:
        raise ValueError("CSV пустой или без заголовка. Нужны хотя бы колонки external_id, local_ip, protocol_version, local_key.")

    normalized_fieldnames = {str(name or "").strip().lower() for name in reader.fieldnames}
    if "external_id" not in normalized_fieldnames:
        raise ValueError("В CSV нет колонки external_id. Возьми devices-lan-seed и дополни его, тогда импорт пройдёт без шаманства.")

    devices = db.execute(
        select(Device).where(Device.is_deleted.is_(False)).order_by(Device.id.asc())
    ).scalars().all()
    devices_by_external_id = {device.external_id: device for device in devices if device.external_id}

    for row_number, raw_row in enumerate(reader, start=2):
        row = {str(key or "").strip().lower(): str(value or "") for key, value in raw_row.items()}
        if not any(value.strip() for value in row.values()):
            result.skipped_total += 1
            continue
        result.rows_total += 1
        external_id = row.get("external_id", "").strip()
        if not external_id:
            result.errors.append(f"Строка {row_number}: пустой external_id.")
            continue
        device = devices_by_external_id.get(external_id)
        if device is None:
            result.unmatched_total += 1
            if external_id not in result.unmatched_external_ids:
                result.unmatched_external_ids.append(external_id)
            continue

        existing = get_device_lan_config(db, device.id)
        incoming_ip = (row.get("local_ip") or row.get("ip") or "").strip()
        incoming_version = (row.get("protocol_version") or row.get("version") or "").strip() or existing.protocol_version
        incoming_key = (row.get("local_key") or row.get("key") or "").strip()
        local_enabled = _coalesce_bool(row.get("local_enabled") or row.get("enabled"), existing.local_enabled)
        prefer_local = _coalesce_bool(row.get("prefer_local") or row.get("prefer_lan"), existing.prefer_local)
        clear_local_key = _parse_bool(row.get("clear_local_key"))

        before = (
            existing.local_ip,
            existing.protocol_version,
            existing.local_key,
            existing.local_enabled,
            existing.prefer_local,
        )
        config = save_device_lan_config(
            db,
            device_id=device.id,
            local_ip=incoming_ip or existing.local_ip,
            protocol_version=incoming_version,
            local_key=incoming_key,
            local_enabled=local_enabled,
            prefer_local=prefer_local,
            preserve_existing_key=True,
            clear_local_key=clear_local_key,
        )
        after = (
            config.local_ip,
            config.protocol_version,
            config.local_key,
            config.local_enabled,
            config.prefer_local,
        )
        result.matched_total += 1
        if before == after:
            result.unchanged_total += 1
        else:
            result.changed_total += 1

        if incoming_key or clear_local_key:
            source = (row.get("key_source") or row.get("source") or "csv_import").strip() or "csv_import"
            record_device_lan_fetch(db, device.id, source=source, cloud_ip=config.local_ip)
            if incoming_key:
                result.key_updates_total += 1

    return result


def batch_probe_local_devices(db: Session, *, scope: str = "enabled_ready") -> DeviceLanBatchProbeResult:
    normalized_scope = (scope or "enabled_ready").strip().lower()
    if normalized_scope not in {"enabled_ready", "complete_any"}:
        normalized_scope = "enabled_ready"

    devices = db.execute(
        select(Device)
        .where(Device.is_deleted.is_(False), Device.provider == ProviderType.TUYA_CLOUD)
        .order_by(Device.name.asc(), Device.id.asc())
    ).scalars().all()

    result = DeviceLanBatchProbeResult(scope=normalized_scope)
    for device in devices:
        config = get_device_lan_config(db, device.id)
        if not config.is_complete:
            result.skipped_total += 1
            continue
        if normalized_scope == "enabled_ready" and not config.local_enabled:
            result.skipped_total += 1
            continue

        result.candidates_total += 1
        try:
            probe = reprobe_device_lan_profile(db, device)
            result.success_total += 1
            result.items.append(
                DeviceLanBatchProbeItem(
                    device_id=device.id,
                    display_name=device.display_name,
                    local_ip=probe.config.local_ip,
                    protocol_version=probe.config.protocol_version,
                    status="success",
                    message=probe.probe_message,
                )
            )
        except DeviceLanKeyError as exc:
            latest = get_device_lan_config(db, device.id)
            result.error_total += 1
            result.items.append(
                DeviceLanBatchProbeItem(
                    device_id=device.id,
                    display_name=device.display_name,
                    local_ip=latest.local_ip,
                    protocol_version=latest.protocol_version,
                    status="error",
                    message=str(exc),
                )
            )
    return result


def _detect_dialect(text: str) -> csv.Dialect:
    sample = text[:4096] or "external_id,local_ip,protocol_version,local_key\n"
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        return csv.get_dialect("excel")


def _decode_csv_bytes(content: bytes) -> str:
    payload = content or b""
    for encoding in _ALLOWED_IMPORT_ENCODINGS:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV не удалось прочитать как UTF-8/UTF-8-SIG/CP1251. Сохрани файл в UTF-8 и попробуй ещё раз.")


def _parse_bool(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on", "да"}


def _coalesce_bool(raw: str | None, current: bool) -> bool:
    value = str(raw or "").strip()
    if not value:
        return current
    return _parse_bool(value)
