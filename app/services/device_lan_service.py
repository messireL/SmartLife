from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Device
from app.services.runtime_config_service import get_setting_value, set_setting_value

_ALLOWED_PROTOCOL_VERSIONS = {"3.1", "3.2", "3.3", "3.4", "3.5"}


def _device_lan_key(device_id: int, suffix: str) -> str:
    return f"device.{int(device_id)}.lan.{suffix}"


@dataclass(slots=True)
class DeviceLanConfig:
    device_id: int
    local_ip: str
    protocol_version: str
    local_key: str
    local_enabled: bool
    prefer_local: bool

    @property
    def has_local_key(self) -> bool:
        return bool((self.local_key or "").strip())

    @property
    def local_key_masked(self) -> str:
        value = (self.local_key or "").strip()
        if not value:
            return "не задан"
        if len(value) <= 6:
            return "*" * len(value)
        return f"{value[:3]}***{value[-3:]}"

    @property
    def is_complete(self) -> bool:
        return bool((self.local_ip or "").strip() and (self.protocol_version or "").strip() and (self.local_key or "").strip())

    @property
    def status_label(self) -> str:
        if not self.local_enabled:
            return "LAN выключен"
        if self.is_complete:
            return "готов"
        return "неполная конфигурация"

    @property
    def local_mode_label(self) -> str:
        if not self.local_enabled:
            return "Выключен"
        if self.prefer_local:
            return "Предпочитать LAN"
        return "LAN как fallback"

    @property
    def can_switch_locally(self) -> bool:
        return self.local_enabled and self.is_complete


DEFAULT_DEVICE_LAN_CONFIG = DeviceLanConfig(
    device_id=0,
    local_ip="",
    protocol_version="3.3",
    local_key="",
    local_enabled=False,
    prefer_local=False,
)


def get_device_lan_config(db: Session, device_id: int) -> DeviceLanConfig:
    return DeviceLanConfig(
        device_id=int(device_id),
        local_ip=get_setting_value(db, _device_lan_key(device_id, "ip"), "").strip(),
        protocol_version=_normalize_protocol_version(get_setting_value(db, _device_lan_key(device_id, "version"), "3.3")),
        local_key=get_setting_value(db, _device_lan_key(device_id, "key"), "").strip(),
        local_enabled=_parse_bool(get_setting_value(db, _device_lan_key(device_id, "enabled"), "no")),
        prefer_local=_parse_bool(get_setting_value(db, _device_lan_key(device_id, "prefer_local"), "no")),
    )


def get_device_lan_config_for_device(db: Session, device: Device | None) -> DeviceLanConfig:
    if device is None:
        return DEFAULT_DEVICE_LAN_CONFIG
    return get_device_lan_config(db, device.id)


def save_device_lan_config(
    db: Session,
    *,
    device_id: int,
    local_ip: str,
    protocol_version: str,
    local_key: str,
    local_enabled: bool,
    prefer_local: bool,
    preserve_existing_key: bool = True,
    clear_local_key: bool = False,
) -> DeviceLanConfig:
    ip_value = (local_ip or "").strip()
    version_value = _normalize_protocol_version(protocol_version)
    existing = get_device_lan_config(db, device_id)

    if clear_local_key:
        key_value = ""
    else:
        incoming_key = (local_key or "").strip()
        if incoming_key:
            key_value = incoming_key
        elif preserve_existing_key:
            key_value = existing.local_key
        else:
            key_value = ""

    set_setting_value(db, _device_lan_key(device_id, "ip"), ip_value)
    set_setting_value(db, _device_lan_key(device_id, "version"), version_value)
    set_setting_value(db, _device_lan_key(device_id, "key"), key_value)
    set_setting_value(db, _device_lan_key(device_id, "enabled"), "yes" if local_enabled else "no")
    set_setting_value(db, _device_lan_key(device_id, "prefer_local"), "yes" if prefer_local else "no")
    db.commit()
    return get_device_lan_config(db, device_id)


def has_local_switch_bridge(db: Session, device: Device | None) -> bool:
    if device is None:
        return False
    config = get_device_lan_config(db, device.id)
    if not config.can_switch_locally:
        return False
    return any(_is_switch_like_code(code) for code in device.control_codes)


def _parse_bool(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_protocol_version(raw: str | None) -> str:
    value = str(raw or "").strip() or "3.3"
    if value not in _ALLOWED_PROTOCOL_VERSIONS:
        return "3.3"
    return value


def _is_switch_like_code(code: str | None) -> bool:
    import re

    if not code:
        return False
    return bool(code == "switch" or re.fullmatch(r"switch_[1-9]\d*", code) or re.fullmatch(r"switch_usb[1-9]\d*", code) or code == "switch_usb")
