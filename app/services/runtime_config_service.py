from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppSetting, ProviderType
from app.services.tariff_service import get_tariff_display, get_tariff_windows

RUNTIME_KEY_PROVIDER = "provider"
RUNTIME_KEY_TUYA_BASE_URL = "tuya.base_url"
RUNTIME_KEY_TUYA_ACCESS_ID = "tuya.access_id"
RUNTIME_KEY_TUYA_ACCESS_SECRET = "tuya.access_secret"
RUNTIME_KEY_TUYA_PROJECT_CODE = "tuya.project_code"

LEGACY_RUNTIME_KEY_TARIFF_PRICE = "tariff.price_per_kwh"
RUNTIME_KEY_TARIFF_MODE = "tariff.mode"
RUNTIME_KEY_TARIFF_CURRENCY = "tariff.currency"
RUNTIME_KEY_TARIFF_FLAT_PRICE = "tariff.flat.price_per_kwh"
RUNTIME_KEY_TARIFF_TWO_DAY_PRICE = "tariff.two_zone.day_price_per_kwh"
RUNTIME_KEY_TARIFF_TWO_NIGHT_PRICE = "tariff.two_zone.night_price_per_kwh"
RUNTIME_KEY_TARIFF_TWO_DAY_START = "tariff.two_zone.day_start"
RUNTIME_KEY_TARIFF_TWO_NIGHT_START = "tariff.two_zone.night_start"
RUNTIME_KEY_TARIFF_THREE_DAY_PRICE = "tariff.three_zone.day_price_per_kwh"
RUNTIME_KEY_TARIFF_THREE_NIGHT_PRICE = "tariff.three_zone.night_price_per_kwh"
RUNTIME_KEY_TARIFF_THREE_PEAK_PRICE = "tariff.three_zone.peak_price_per_kwh"
RUNTIME_KEY_TARIFF_THREE_DAY_START = "tariff.three_zone.day_start"
RUNTIME_KEY_TARIFF_THREE_NIGHT_START = "tariff.three_zone.night_start"
RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_START = "tariff.three_zone.peak_morning_start"
RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_END = "tariff.three_zone.peak_morning_end"
RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_START = "tariff.three_zone.peak_evening_start"
RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_END = "tariff.three_zone.peak_evening_end"


@dataclass(slots=True)
class RuntimeConfig:
    provider: str
    tuya_base_url: str
    tuya_access_id: str
    tuya_access_secret: str
    tuya_project_code: str
    tariff_mode: str
    tariff_currency: str
    tariff_flat_price_per_kwh: str
    tariff_two_day_price_per_kwh: str
    tariff_two_night_price_per_kwh: str
    tariff_two_day_start: str
    tariff_two_night_start: str
    tariff_three_day_price_per_kwh: str
    tariff_three_night_price_per_kwh: str
    tariff_three_peak_price_per_kwh: str
    tariff_three_day_start: str
    tariff_three_night_start: str
    tariff_three_peak_morning_start: str
    tariff_three_peak_morning_end: str
    tariff_three_peak_evening_start: str
    tariff_three_peak_evening_end: str

    @property
    def tuya_access_id_masked(self) -> str:
        value = (self.tuya_access_id or "").strip()
        if not value:
            return "не задан"
        if len(value) <= 6:
            return "*" * len(value)
        return f"{value[:3]}***{value[-3:]}"

    @property
    def tuya_access_secret_masked(self) -> str:
        value = (self.tuya_access_secret or "").strip()
        if not value:
            return "не задан"
        return "•" * 8

    @property
    def tuya_is_configured(self) -> bool:
        return bool((self.tuya_access_id or "").strip() and (self.tuya_access_secret or "").strip())

    @property
    def tariff_mode_label(self) -> str:
        return {
            "flat": "Единый",
            "two_zone": "Двухзонный",
            "three_zone": "Трёхзонный",
        }.get(self.tariff_mode, "Единый")

    @property
    def tariff_price_decimal(self) -> Decimal:
        return self.tariff_primary_price_decimal

    @property
    def tariff_primary_price_decimal(self) -> Decimal:
        mapping = {
            "flat": self.tariff_flat_price_per_kwh,
            "two_zone": self.tariff_two_day_price_per_kwh,
            "three_zone": self.tariff_three_day_price_per_kwh,
        }
        raw = (mapping.get(self.tariff_mode) or "0.00").strip()
        try:
            return Decimal(raw).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")

    @property
    def tariff_display(self) -> str:
        return get_tariff_display(self)

    @property
    def tariff_windows(self) -> list[str]:
        return get_tariff_windows(self)


def _get_setting_row(db: Session, key: str) -> AppSetting | None:
    return db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()


def get_setting_value(db: Session, key: str, default: str = "") -> str:
    row = _get_setting_row(db, key)
    if row is None or row.value is None:
        return default
    return str(row.value)


def set_setting_value(db: Session, key: str, value: str | None) -> None:
    row = _get_setting_row(db, key)
    if row is None:
        row = AppSetting(key=key)
        db.add(row)
    row.value = value


def set_runtime_values(db: Session, values: dict[str, str | None]) -> None:
    for key, value in values.items():
        set_setting_value(db, key, value)
    db.commit()


def _build_runtime_config(db: Session) -> RuntimeConfig:
    settings = get_settings()
    return RuntimeConfig(
        provider=get_setting_value(db, RUNTIME_KEY_PROVIDER, settings.smartlife_provider or ProviderType.DEMO.value),
        tuya_base_url=get_setting_value(db, RUNTIME_KEY_TUYA_BASE_URL, settings.smartlife_tuya_base_url or "https://openapi.tuyaeu.com"),
        tuya_access_id=get_setting_value(db, RUNTIME_KEY_TUYA_ACCESS_ID, settings.smartlife_tuya_access_id or ""),
        tuya_access_secret=get_setting_value(db, RUNTIME_KEY_TUYA_ACCESS_SECRET, settings.smartlife_tuya_access_secret or ""),
        tuya_project_code=get_setting_value(db, RUNTIME_KEY_TUYA_PROJECT_CODE, settings.smartlife_tuya_project_code or ""),
        tariff_mode=get_setting_value(db, RUNTIME_KEY_TARIFF_MODE, "flat"),
        tariff_currency=get_setting_value(db, RUNTIME_KEY_TARIFF_CURRENCY, "₽"),
        tariff_flat_price_per_kwh=get_setting_value(db, RUNTIME_KEY_TARIFF_FLAT_PRICE, "0.00"),
        tariff_two_day_price_per_kwh=get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_DAY_PRICE, "0.00"),
        tariff_two_night_price_per_kwh=get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_NIGHT_PRICE, "0.00"),
        tariff_two_day_start=get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_DAY_START, "07:00"),
        tariff_two_night_start=get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_NIGHT_START, "23:00"),
        tariff_three_day_price_per_kwh=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_DAY_PRICE, "0.00"),
        tariff_three_night_price_per_kwh=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_NIGHT_PRICE, "0.00"),
        tariff_three_peak_price_per_kwh=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_PRICE, "0.00"),
        tariff_three_day_start=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_DAY_START, "07:00"),
        tariff_three_night_start=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_NIGHT_START, "23:00"),
        tariff_three_peak_morning_start=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_START, "07:00"),
        tariff_three_peak_morning_end=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_END, "10:00"),
        tariff_three_peak_evening_start=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_START, "17:00"),
        tariff_three_peak_evening_end=get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_END, "21:00"),
    )


def bootstrap_runtime_settings(db: Session) -> RuntimeConfig:
    settings = get_settings()
    legacy_tariff_price = get_setting_value(db, LEGACY_RUNTIME_KEY_TARIFF_PRICE, "0.00")
    defaults = {
        RUNTIME_KEY_PROVIDER: settings.smartlife_provider or ProviderType.DEMO.value,
        RUNTIME_KEY_TUYA_BASE_URL: settings.smartlife_tuya_base_url or "https://openapi.tuyaeu.com",
        RUNTIME_KEY_TUYA_ACCESS_ID: settings.smartlife_tuya_access_id or "",
        RUNTIME_KEY_TUYA_ACCESS_SECRET: settings.smartlife_tuya_access_secret or "",
        RUNTIME_KEY_TUYA_PROJECT_CODE: settings.smartlife_tuya_project_code or "",
        RUNTIME_KEY_TARIFF_MODE: "flat",
        RUNTIME_KEY_TARIFF_CURRENCY: "₽",
        RUNTIME_KEY_TARIFF_FLAT_PRICE: legacy_tariff_price or "0.00",
        RUNTIME_KEY_TARIFF_TWO_DAY_PRICE: "0.00",
        RUNTIME_KEY_TARIFF_TWO_NIGHT_PRICE: "0.00",
        RUNTIME_KEY_TARIFF_TWO_DAY_START: "07:00",
        RUNTIME_KEY_TARIFF_TWO_NIGHT_START: "23:00",
        RUNTIME_KEY_TARIFF_THREE_DAY_PRICE: "0.00",
        RUNTIME_KEY_TARIFF_THREE_NIGHT_PRICE: "0.00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_PRICE: "0.00",
        RUNTIME_KEY_TARIFF_THREE_DAY_START: "07:00",
        RUNTIME_KEY_TARIFF_THREE_NIGHT_START: "23:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_START: "07:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_END: "10:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_START: "17:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_END: "21:00",
    }
    changed = False
    for key, default_value in defaults.items():
        row = _get_setting_row(db, key)
        if row is None:
            db.add(AppSetting(key=key, value=default_value))
            changed = True
    if changed:
        db.commit()
    return _build_runtime_config(db)


def get_runtime_config(db: Session) -> RuntimeConfig:
    bootstrap_runtime_settings(db)
    return _build_runtime_config(db)


def get_runtime_provider_name(db: Session) -> str:
    return get_runtime_config(db).provider


def configure_tuya_cloud(db: Session, *, base_url: str, access_id: str, access_secret: str, project_code: str = "") -> RuntimeConfig:
    set_runtime_values(
        db,
        {
            RUNTIME_KEY_PROVIDER: ProviderType.TUYA_CLOUD.value,
            RUNTIME_KEY_TUYA_BASE_URL: base_url.strip(),
            RUNTIME_KEY_TUYA_ACCESS_ID: access_id.strip(),
            RUNTIME_KEY_TUYA_ACCESS_SECRET: access_secret.strip(),
            RUNTIME_KEY_TUYA_PROJECT_CODE: project_code.strip(),
        },
    )
    return get_runtime_config(db)


def configure_demo_provider(db: Session) -> RuntimeConfig:
    set_runtime_values(db, {RUNTIME_KEY_PROVIDER: ProviderType.DEMO.value})
    return get_runtime_config(db)


def configure_tariff_settings(db: Session, *, values: dict[str, str]) -> RuntimeConfig:
    normalized_values = {key: (value or "").strip() for key, value in values.items()}
    set_runtime_values(db, normalized_values)
    return get_runtime_config(db)
