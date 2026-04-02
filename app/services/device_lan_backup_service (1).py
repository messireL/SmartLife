from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.version import APP_VERSION
from app.db.models import Device
from app.services.device_lan_service import get_device_lan_config, save_device_lan_config, save_device_lan_metadata

LAN_BACKUP_DIR = Path("/app/backups/lan")


@dataclass(slots=True)
class DeviceLanBackupImportResult:
    filename: str
    rows_total: int = 0
    matched_total: int = 0
    changed_total: int = 0
    unchanged_total: int = 0
    skipped_total: int = 0
    unmatched_total: int = 0
    key_updates_total: int = 0
    mac_updates_total: int = 0
    errors: list[str] = field(default_factory=list)
    unmatched_external_ids: list[str] = field(default_factory=list)


def build_device_lan_backup_payload(db: Session) -> dict[str, object]:
    devices = db.execute(
        select(Device).where(Device.is_deleted.is_(False)).order_by(Device.name.asc(), Device.id.asc())
    ).scalars().all()

    items: list[dict[str, object]] = []
    for device in devices:
        config = get_device_lan_config(db, device.id)
        if not (
            config.local_ip
            or config.local_key
            or config.local_enabled
            or config.prefer_local
            or config.local_mac
            or config.last_probe_status
            or config.key_source
        ):
            continue
        items.append(
            {
                "device_id": device.id,
                "external_id": device.external_id,
                "display_name": device.display_name,
                "provider_name": device.name,
                "model": device.model or device.product_name or "",
                "room_name": device.display_room_name or "",
                "local_ip": config.local_ip,
                "protocol_version": config.protocol_version,
                "local_key": config.local_key,
                "local_enabled": config.local_enabled,
                "prefer_local": config.prefer_local,
                "cloud_ip": config.cloud_ip,
                "local_mac": config.local_mac,
                "key_source": config.key_source,
                "key_refreshed_at": config.key_refreshed_at.isoformat() if config.key_refreshed_at else "",
                "last_probe_at": config.last_probe_at.isoformat() if config.last_probe_at else "",
                "last_probe_status": config.last_probe_status,
                "last_probe_message": config.last_probe_message,
            }
        )

    return {
        "kind": "smartlife_device_lan_backup",
        "version": 1,
        "app_version": APP_VERSION,
        "exported_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "items_total": len(items),
        "items": items,
    }


def dump_device_lan_backup_json(db: Session) -> tuple[str, bytes]:
    payload = build_device_lan_backup_payload(db)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"smartlife-device-lan-backup-{timestamp}.json"
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return filename, content


def save_device_lan_backup_snapshot(db: Session) -> dict[str, object]:
    filename, content = dump_device_lan_backup_json(db)
    LAN_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = LAN_BACKUP_DIR / filename
    path.write_bytes(content)
    return {
        "filename": filename,
        "path": str(path),
        "size_bytes": len(content),
    }


def import_device_lan_backup_json(db: Session, *, filename: str, content: bytes) -> DeviceLanBackupImportResult:
    result = DeviceLanBackupImportResult(filename=filename or "smartlife-device-lan-backup.json")
    try:
        payload = json.loads((content or b"").decode("utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("JSON LAN-резерва не читается. Сохрани файл в UTF-8 и попробуй ещё раз.") from exc

    if not isinstance(payload, dict):
        raise ValueError("JSON LAN-резерва должен быть объектом с полем items.")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("В JSON LAN-резерва нет массива items.")

    devices = db.execute(
        select(Device).where(Device.is_deleted.is_(False)).order_by(Device.id.asc())
    ).scalars().all()
    devices_by_external_id = {device.external_id: device for device in devices if device.external_id}

    for index, raw_item in enumerate(items, start=1):
        if not isinstance(raw_item, dict):
            result.errors.append(f"Элемент {index}: ожидался объект, а не {type(raw_item).__name__}.")
            continue
        result.rows_total += 1
        external_id = str(raw_item.get("external_id") or "").strip()
        if not external_id:
            result.errors.append(f"Элемент {index}: пустой external_id.")
            continue
        device = devices_by_external_id.get(external_id)
        if device is None:
            result.unmatched_total += 1
            if external_id not in result.unmatched_external_ids:
                result.unmatched_external_ids.append(external_id)
            continue

        existing = get_device_lan_config(db, device.id)
        incoming_ip = str(raw_item.get("local_ip") or "").strip()
        incoming_version = str(raw_item.get("protocol_version") or existing.protocol_version or "3.3").strip() or existing.protocol_version
        incoming_key = str(raw_item.get("local_key") or "").strip()
        local_enabled = bool(raw_item.get("local_enabled"))
        prefer_local = bool(raw_item.get("prefer_local"))
        before = (
            existing.local_ip,
            existing.protocol_version,
            existing.local_key,
            existing.local_enabled,
            existing.prefer_local,
            existing.local_mac,
            existing.key_source,
            existing.last_probe_status,
            existing.last_probe_message,
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
            clear_local_key=False,
        )
        metadata = save_device_lan_metadata(
            db,
            device_id=device.id,
            cloud_ip=str(raw_item.get("cloud_ip") or config.cloud_ip or "").strip(),
            mac=str(raw_item.get("local_mac") or "").strip(),
            key_source=str(raw_item.get("key_source") or config.key_source or "backup_import").strip() or "backup_import",
            key_refreshed_at=str(raw_item.get("key_refreshed_at") or "").strip(),
            last_probe_at=str(raw_item.get("last_probe_at") or "").strip(),
            last_probe_status=str(raw_item.get("last_probe_status") or "").strip(),
            last_probe_message=str(raw_item.get("last_probe_message") or "").strip(),
        )
        after = (
            metadata.local_ip,
            metadata.protocol_version,
            metadata.local_key,
            metadata.local_enabled,
            metadata.prefer_local,
            metadata.local_mac,
            metadata.key_source,
            metadata.last_probe_status,
            metadata.last_probe_message,
        )
        result.matched_total += 1
        if before == after:
            result.unchanged_total += 1
        else:
            result.changed_total += 1
        if incoming_key:
            result.key_updates_total += 1
        if str(raw_item.get("local_mac") or "").strip():
            result.mac_updates_total += 1

    return result
