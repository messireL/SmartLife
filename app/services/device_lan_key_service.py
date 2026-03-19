from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Device, ProviderType
from app.integrations.tuya_provider import TuyaApiError, TuyaCloudProvider
from app.services.device_lan_service import (
    DeviceLanConfig,
    get_device_lan_config,
    record_device_lan_fetch,
    record_device_lan_probe,
    save_device_lan_config,
)
from app.services.tuya_local_service import TuyaLocalError, probe_local_device


class DeviceLanKeyError(RuntimeError):
    pass


@dataclass(slots=True)
class DeviceLanKeyFetchResult:
    config: DeviceLanConfig
    fetched_ip: str
    local_key_received: bool
    probe_attempted: bool
    probe_success: bool
    probe_message: str
    cloud_payload: dict[str, Any]


@dataclass(slots=True)
class DeviceLanProbeRefreshResult:
    config: DeviceLanConfig
    probe_success: bool
    probe_message: str



def refresh_device_lan_key_from_tuya(db: Session, device: Device) -> DeviceLanKeyFetchResult:
    if device.provider != ProviderType.TUYA_CLOUD:
        raise DeviceLanKeyError("LAN-ключ из Tuya можно запросить только для Tuya Cloud устройств.")

    existing = get_device_lan_config(db, device.id)
    try:
        provider = TuyaCloudProvider()
        payload = provider.client.get_device_details(device.external_id)
    except (TuyaApiError, ValueError) as exc:
        raise DeviceLanKeyError(str(exc)) from exc

    fetched_key = str(payload.get("local_key") or payload.get("localKey") or "").strip()
    fetched_ip = str(payload.get("ip") or "").strip()
    if not fetched_key:
        raise DeviceLanKeyError(
            "Tuya вернула карточку устройства, но без local_key. Проверь device details в облаке и повтори запрос позже."
        )

    saved_ip = fetched_ip or existing.local_ip
    config = save_device_lan_config(
        db,
        device_id=device.id,
        local_ip=saved_ip,
        protocol_version=existing.protocol_version,
        local_key=fetched_key,
        local_enabled=existing.local_enabled,
        prefer_local=existing.prefer_local,
        preserve_existing_key=False,
    )
    record_device_lan_fetch(db, device.id, source="tuya_cloud", cloud_ip=fetched_ip)

    probe_attempted = bool(config.local_ip and config.has_local_key)
    probe_success = False
    probe_message = "IP не получен из Tuya: local key сохранён, но адрес нужно внести или уточнить вручную."

    if probe_attempted:
        try:
            probe = probe_local_device(
                device_id=device.external_id,
                config=config,
                candidate_versions=(existing.protocol_version, "3.5", "3.4", "3.3", "3.2", "3.1"),
            )
            config = save_device_lan_config(
                db,
                device_id=device.id,
                local_ip=probe.ip,
                protocol_version=probe.protocol_version,
                local_key=fetched_key,
                local_enabled=True,
                prefer_local=True,
                preserve_existing_key=False,
            )
            probe_success = True
            probe_message = (
                f"LAN-probe успешен: {probe.ip} · v{probe.protocol_version}. "
                "Для switch-команд устройство уже можно уводить с облака на локальный контур."
            )
            record_device_lan_probe(db, device.id, status="success", message=probe_message)
        except TuyaLocalError as exc:
            probe_message = str(exc)
            record_device_lan_probe(db, device.id, status="error", message=probe_message)
            config = get_device_lan_config(db, device.id)
    else:
        record_device_lan_probe(db, device.id, status="skipped", message=probe_message)
        config = get_device_lan_config(db, device.id)

    return DeviceLanKeyFetchResult(
        config=config,
        fetched_ip=fetched_ip,
        local_key_received=True,
        probe_attempted=probe_attempted,
        probe_success=probe_success,
        probe_message=probe_message,
        cloud_payload=payload,
    )



def reprobe_device_lan_profile(db: Session, device: Device) -> DeviceLanProbeRefreshResult:
    if device.provider != ProviderType.TUYA_CLOUD:
        raise DeviceLanKeyError("LAN-probe сейчас поддержан только для Tuya Cloud устройств.")
    config = get_device_lan_config(db, device.id)
    if not config.local_ip:
        raise DeviceLanKeyError("Сначала заполни локальный IP устройства.")
    if not config.has_local_key:
        raise DeviceLanKeyError("Сначала заполни local key устройства.")

    try:
        probe = probe_local_device(
            device_id=device.external_id,
            config=config,
            candidate_versions=(config.protocol_version, "3.5", "3.4", "3.3", "3.2", "3.1"),
        )
        config = save_device_lan_config(
            db,
            device_id=device.id,
            local_ip=probe.ip,
            protocol_version=probe.protocol_version,
            local_key=config.local_key,
            local_enabled=True,
            prefer_local=True,
            preserve_existing_key=False,
        )
        message = f"LAN-probe успешен: {probe.ip} · v{probe.protocol_version}."
        record_device_lan_probe(db, device.id, status="success", message=message)
        return DeviceLanProbeRefreshResult(config=config, probe_success=True, probe_message=message)
    except TuyaLocalError as exc:
        message = str(exc)
        record_device_lan_probe(db, device.id, status="error", message=message)
        raise DeviceLanKeyError(message) from exc
