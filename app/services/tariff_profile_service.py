from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Device
from app.services.runtime_config_service import (
    TariffPlan,
    RuntimeConfig,
    get_setting_value,
    set_setting_value,
)

TARIFF_PROFILE_CATALOG_KEY = "tariff.profile.catalog_json"
SYSTEM_TARIFF_PROFILE_KEY = "__system__"

PROFILE_FIELDS = (
    "tariff_mode",
    "tariff_currency",
    "tariff_flat_price_per_kwh",
    "tariff_two_day_price_per_kwh",
    "tariff_two_night_price_per_kwh",
    "tariff_two_day_start",
    "tariff_two_night_start",
    "tariff_three_day_price_per_kwh",
    "tariff_three_night_price_per_kwh",
    "tariff_three_peak_price_per_kwh",
    "tariff_three_day_start",
    "tariff_three_night_start",
    "tariff_three_peak_morning_start",
    "tariff_three_peak_morning_end",
    "tariff_three_peak_evening_start",
    "tariff_three_peak_evening_end",
)

DEFAULT_PROFILE_LABEL = "Системный тариф"


def _slugify(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", (value or "").strip().lower(), flags=re.UNICODE)
    raw = raw.strip("-")
    return raw[:48] or "profile"



def _profile_payload_from_runtime(runtime: RuntimeConfig) -> dict[str, str]:
    return {field: str(getattr(runtime, field) or "") for field in PROFILE_FIELDS}



def _sanitize_profile(item: dict[str, Any], base_runtime: RuntimeConfig) -> dict[str, str]:
    payload = _profile_payload_from_runtime(base_runtime)
    payload.update({field: str(item.get(field) or payload[field]) for field in PROFILE_FIELDS})
    key = _slugify(str(item.get("key") or item.get("name") or "profile"))
    name = (str(item.get("name") or "").strip() or key).strip()
    payload.update(
        {
            "key": key,
            "name": name,
            "note": str(item.get("note") or "").strip(),
        }
    )
    return payload



def _read_catalog(db: Session, base_runtime: RuntimeConfig) -> list[dict[str, str]]:
    raw = get_setting_value(db, TARIFF_PROFILE_CATALOG_KEY, "")
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        sanitized = _sanitize_profile(item, base_runtime)
        if sanitized["key"] in seen:
            continue
        seen.add(sanitized["key"])
        cleaned.append(sanitized)
    cleaned.sort(key=lambda row: row["name"].lower())
    return cleaned



def _write_catalog(db: Session, items: list[dict[str, str]]) -> None:
    set_setting_value(db, TARIFF_PROFILE_CATALOG_KEY, json.dumps(items, ensure_ascii=False, indent=2, sort_keys=True))
    db.commit()



def get_tariff_profile_catalog(db: Session, base_runtime: RuntimeConfig) -> list[dict[str, str]]:
    return _read_catalog(db, base_runtime)



def get_tariff_profile(db: Session, key: str, base_runtime: RuntimeConfig) -> dict[str, str] | None:
    key = (key or "").strip()
    if not key or key == SYSTEM_TARIFF_PROFILE_KEY:
        return None
    for item in _read_catalog(db, base_runtime):
        if item["key"] == key:
            return item
    return None



def _assignment_counts(db: Session) -> dict[str | None, int]:
    rows = db.execute(
        select(Device.tariff_profile_key, func.count())
        .where(Device.is_deleted.is_(False))
        .group_by(Device.tariff_profile_key)
    ).all()
    return {key: int(count) for key, count in rows}



def list_tariff_profiles(db: Session, base_runtime: RuntimeConfig) -> list[dict[str, Any]]:
    catalog = _read_catalog(db, base_runtime)
    counts = _assignment_counts(db)
    result: list[dict[str, Any]] = [
        {
            "key": SYSTEM_TARIFF_PROFILE_KEY,
            "name": DEFAULT_PROFILE_LABEL,
            "note": "Использует общий тариф из системных настроек.",
            "is_system": True,
            "assigned_count": counts.get(None, 0) + sum(count for key, count in counts.items() if key and not any(p["key"] == key for p in catalog)),
            **_profile_payload_from_runtime(base_runtime),
            "tariff_mode_label": base_runtime.tariff_mode_label,
            "tariff_display": base_runtime.tariff_display,
        }
    ]
    for item in catalog:
        runtime = build_runtime_from_profile(base_runtime, item)
        result.append(
            {
                **item,
                "is_system": False,
                "assigned_count": counts.get(item["key"], 0),
                "tariff_mode_label": runtime.tariff_mode_label,
                "tariff_display": runtime.tariff_display,
            }
        )
    return result



def build_runtime_from_profile(base_runtime: RuntimeConfig, profile: dict[str, str]) -> RuntimeConfig:
    payload = _profile_payload_from_runtime(base_runtime)
    payload.update({field: str(profile.get(field) or payload[field]) for field in PROFILE_FIELDS})
    plan = TariffPlan(
        effective_from=base_runtime.tariff_effective_from or date.today().isoformat(),
        **payload,
    )
    return replace(
        base_runtime,
        tariff_plan_history=(plan,),
        **payload,
    )



def get_tariff_runtime_map(db: Session, base_runtime: RuntimeConfig) -> dict[str, RuntimeConfig]:
    mapping = {SYSTEM_TARIFF_PROFILE_KEY: base_runtime}
    for item in _read_catalog(db, base_runtime):
        mapping[item["key"]] = build_runtime_from_profile(base_runtime, item)
    return mapping



def get_device_tariff_runtime(device: Device, base_runtime: RuntimeConfig, runtime_map: dict[str, RuntimeConfig] | None = None) -> RuntimeConfig:
    mapping = runtime_map or {SYSTEM_TARIFF_PROFILE_KEY: base_runtime}
    key = (device.tariff_profile_key or "").strip()
    return mapping.get(key) or base_runtime



def get_device_tariff_profile_choice(device: Device, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    selected_key = (device.tariff_profile_key or "").strip() or SYSTEM_TARIFF_PROFILE_KEY
    for item in profiles:
        if item["key"] == selected_key:
            return item
    return profiles[0]



def upsert_tariff_profile(db: Session, base_runtime: RuntimeConfig, values: dict[str, str]) -> dict[str, str]:
    catalog = _read_catalog(db, base_runtime)
    profile_key = (values.get("profile_key") or "").strip()
    profile_name = (values.get("profile_name") or "").strip()
    if not profile_name:
        raise ValueError("Название тарифного профиля обязательно.")
    desired_key = _slugify(profile_key or profile_name)
    if desired_key == SYSTEM_TARIFF_PROFILE_KEY:
        desired_key = _slugify(f"{profile_name}-profile")
    payload = {field: str(values.get(field) or "") for field in PROFILE_FIELDS}
    payload.update({"key": desired_key, "name": profile_name, "note": str(values.get("profile_note") or "").strip()})

    existing_index = next((idx for idx, item in enumerate(catalog) if item["key"] == desired_key), None)
    if existing_index is None and profile_key:
        existing_index = next((idx for idx, item in enumerate(catalog) if item["key"] == profile_key), None)
    if existing_index is None and any(item["key"] == desired_key for item in catalog):
        raise ValueError("Тарифный профиль с таким кодом уже существует.")
    sanitized = _sanitize_profile(payload, base_runtime)
    if existing_index is None:
        catalog.append(sanitized)
    else:
        old_key = catalog[existing_index]["key"]
        catalog[existing_index] = sanitized
        if old_key != sanitized["key"]:
            for device in db.scalars(select(Device).where(Device.tariff_profile_key == old_key)).all():
                device.tariff_profile_key = sanitized["key"]
    catalog.sort(key=lambda row: row["name"].lower())
    _write_catalog(db, catalog)
    return sanitized



def delete_tariff_profile(db: Session, base_runtime: RuntimeConfig, key: str) -> bool:
    target = (key or "").strip()
    if not target or target == SYSTEM_TARIFF_PROFILE_KEY:
        return False
    catalog = _read_catalog(db, base_runtime)
    filtered = [item for item in catalog if item["key"] != target]
    if len(filtered) == len(catalog):
        return False
    for device in db.scalars(select(Device).where(Device.tariff_profile_key == target)).all():
        device.tariff_profile_key = None
    _write_catalog(db, filtered)
    return True
