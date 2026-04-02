from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppSetting, Device
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
    prefer_local_explicit: bool
    cloud_ip: str
    local_mac: str
    key_source: str
    key_refreshed_at: datetime | None
    last_probe_at: datetime | None
    last_probe_status: str
    last_probe_message: str

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
    def prefer_local_form_checked(self) -> bool:
        return self.prefer_local or not self.prefer_local_explicit

    @property
    def local_mode_label(self) -> str:
        if not self.local_enabled:
            return "Выключен"
        if self.prefer_local:
            return "Предпочитать LAN"
        return "LAN как fallback"

    @property
    def key_source_label(self) -> str:
        if self.key_source == "tuya_cloud_manual":
            return "Tuya Cloud · вручную"
        if self.key_source == "tuya_cloud":
            return "Tuya Cloud"
        if self.key_source:
            return self.key_source
        return "—"

    @property
    def probe_status_label(self) -> str:
        mapping = {
            "success": "Успешно",
            "error": "Ошибка",
            "skipped": "Пропущено",
        }
        return mapping.get((self.last_probe_status or "").strip().lower(), "—")

    @property
    def can_switch_locally(self) -> bool:
        return self.local_enabled and self.is_complete

    @property
    def has_local_profile(self) -> bool:
        return bool(self.local_enabled and self.is_complete)

    @property
    def is_locally_verified(self) -> bool:
        return (self.last_probe_status or "").strip().lower() == "success"

    @property
    def key_inventory_label(self) -> str:
        return "Key получен" if self.has_local_key else "Без key"

    @property
    def local_inventory_label(self) -> str:
        if self.local_enabled and self.prefer_local and self.is_locally_verified:
            return "Локальный режим"
        if self.local_enabled and self.is_locally_verified:
            return "LAN готов"
        if self.local_enabled:
            return "LAN-профиль"
        if self.has_local_key:
            return "Ключ получен"
        return "LAN не настроен"


DEFAULT_DEVICE_LAN_CONFIG = DeviceLanConfig(
    device_id=0,
    local_ip="",
    protocol_version="3.3",
    local_key="",
    local_enabled=False,
    prefer_local=False,
    prefer_local_explicit=False,
    cloud_ip="",
    local_mac="",
    key_source="",
    key_refreshed_at=None,
    last_probe_at=None,
    last_probe_status="",
    last_probe_message="",
)


def get_device_lan_config(db: Session, device_id: int) -> DeviceLanConfig:
    raw = {
        "ip": get_setting_value(db, _device_lan_key(device_id, "ip"), "").strip(),
        "version": get_setting_value(db, _device_lan_key(device_id, "version"), "3.3").strip(),
        "key": get_setting_value(db, _device_lan_key(device_id, "key"), "").strip(),
        "enabled": get_setting_value(db, _device_lan_key(device_id, "enabled"), "no").strip(),
        "prefer_local": get_setting_value(db, _device_lan_key(device_id, "prefer_local"), "no").strip(),
        "cloud_ip": get_setting_value(db, _device_lan_key(device_id, "cloud_ip"), "").strip(),
        "mac": get_setting_value(db, _device_lan_key(device_id, "mac"), "").strip(),
        "key_source": get_setting_value(db, _device_lan_key(device_id, "key_source"), "").strip(),
        "key_refreshed_at": get_setting_value(db, _device_lan_key(device_id, "key_refreshed_at"), "").strip(),
        "last_probe_at": get_setting_value(db, _device_lan_key(device_id, "last_probe_at"), "").strip(),
        "last_probe_status": get_setting_value(db, _device_lan_key(device_id, "last_probe_status"), "").strip(),
        "last_probe_message": get_setting_value(db, _device_lan_key(device_id, "last_probe_message"), "").strip(),
    }
    prefer_local_key = _device_lan_key(device_id, "prefer_local")
    prefer_local_explicit = _setting_exists(db, prefer_local_key)
    return _build_device_lan_config(device_id=device_id, raw=raw, prefer_local_explicit=prefer_local_explicit)


def get_device_lan_configs_map(db: Session, device_ids: list[int] | tuple[int, ...]) -> dict[int, DeviceLanConfig]:
    normalized_ids = [int(item) for item in device_ids if item is not None]
    if not normalized_ids:
        return {}

    rows = db.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.like("device.%.lan.%"))).all()
    raw_map: dict[int, dict[str, str]] = {device_id: {} for device_id in normalized_ids}
    explicit_prefer_ids: set[int] = set()
    for key, value in rows:
        key_text = str(key or "")
        for device_id in normalized_ids:
            prefix = f"device.{device_id}.lan."
            if not key_text.startswith(prefix):
                continue
            suffix = key_text[len(prefix):]
            raw_map.setdefault(device_id, {})[suffix] = str(value or "")
            if suffix == "prefer_local":
                explicit_prefer_ids.add(device_id)
            break

    return {
        device_id: _build_device_lan_config(
            device_id=device_id,
            raw=raw_map.get(device_id, {}),
            prefer_local_explicit=device_id in explicit_prefer_ids,
        )
        for device_id in normalized_ids
    }


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


def record_device_lan_fetch(db: Session, device_id: int, *, source: str, cloud_ip: str = "", mac: str = "") -> DeviceLanConfig:
    now = datetime.utcnow().replace(microsecond=0)
    set_setting_value(db, _device_lan_key(device_id, "key_source"), (source or "").strip())
    set_setting_value(db, _device_lan_key(device_id, "key_refreshed_at"), now.isoformat())
    if cloud_ip:
        set_setting_value(db, _device_lan_key(device_id, "cloud_ip"), cloud_ip.strip())
    normalized_mac = _normalize_mac(mac)
    if normalized_mac:
        set_setting_value(db, _device_lan_key(device_id, "mac"), normalized_mac)
    db.commit()
    return get_device_lan_config(db, device_id)


def save_device_lan_metadata(
    db: Session,
    *,
    device_id: int,
    cloud_ip: str = "",
    mac: str = "",
    key_source: str = "",
    key_refreshed_at: str = "",
    last_probe_at: str = "",
    last_probe_status: str = "",
    last_probe_message: str = "",
) -> DeviceLanConfig:
    if cloud_ip:
        set_setting_value(db, _device_lan_key(device_id, "cloud_ip"), cloud_ip.strip())
    normalized_mac = _normalize_mac(mac)
    if normalized_mac:
        set_setting_value(db, _device_lan_key(device_id, "mac"), normalized_mac)
    if key_source:
        set_setting_value(db, _device_lan_key(device_id, "key_source"), key_source.strip())
    if key_refreshed_at:
        set_setting_value(db, _device_lan_key(device_id, "key_refreshed_at"), key_refreshed_at.strip())
    if last_probe_at:
        set_setting_value(db, _device_lan_key(device_id, "last_probe_at"), last_probe_at.strip())
    if last_probe_status:
        set_setting_value(db, _device_lan_key(device_id, "last_probe_status"), last_probe_status.strip())
    if last_probe_message:
        set_setting_value(db, _device_lan_key(device_id, "last_probe_message"), last_probe_message.strip())
    db.commit()
    return get_device_lan_config(db, device_id)


def record_device_lan_probe(db: Session, device_id: int, *, status: str, message: str) -> DeviceLanConfig:
    now = datetime.utcnow().replace(microsecond=0)
    set_setting_value(db, _device_lan_key(device_id, "last_probe_at"), now.isoformat())
    set_setting_value(db, _device_lan_key(device_id, "last_probe_status"), (status or "").strip())
    set_setting_value(db, _device_lan_key(device_id, "last_probe_message"), (message or "").strip())
    db.commit()
    return get_device_lan_config(db, device_id)


def _setting_exists(db: Session, key: str) -> bool:
    return db.execute(select(AppSetting.id).where(AppSetting.key == key)).scalar_one_or_none() is not None


def _parse_datetime(raw: str | None) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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


def _normalize_mac(raw: str | None) -> str:
    value = str(raw or "").strip().replace("-", ":")
    if not value:
        return ""
    parts = [part.zfill(2).upper() for part in value.split(":") if part.strip()]
    if len(parts) == 6:
        return ":".join(parts)
    compact = ''.join(ch for ch in value if ch.isalnum())
    if len(compact) == 12:
        compact = compact.upper()
        return ':'.join(compact[i:i+2] for i in range(0, 12, 2))
    return value.upper()


def _build_device_lan_config(*, device_id: int, raw: dict[str, str], prefer_local_explicit: bool) -> DeviceLanConfig:
    return DeviceLanConfig(
        device_id=int(device_id),
        local_ip=str(raw.get("ip") or "").strip(),
        protocol_version=_normalize_protocol_version(raw.get("version") or "3.3"),
        local_key=str(raw.get("key") or "").strip(),
        local_enabled=_parse_bool(raw.get("enabled") or "no"),
        prefer_local=_parse_bool(raw.get("prefer_local") or "no"),
        prefer_local_explicit=prefer_local_explicit,
        cloud_ip=str(raw.get("cloud_ip") or "").strip(),
        local_mac=_normalize_mac(raw.get("mac") or ""),
        key_source=str(raw.get("key_source") or "").strip(),
        key_refreshed_at=_parse_datetime(raw.get("key_refreshed_at") or ""),
        last_probe_at=_parse_datetime(raw.get("last_probe_at") or ""),
        last_probe_status=str(raw.get("last_probe_status") or "").strip(),
        last_probe_message=str(raw.get("last_probe_message") or "").strip(),
    )


def _is_switch_like_code(code: str | None) -> bool:
    import re

    if not code:
        return False
    return bool(code == "switch" or re.fullmatch(r"switch_[1-9]\d*", code) or re.fullmatch(r"switch_usb[1-9]\d*", code) or code == "switch_usb")
