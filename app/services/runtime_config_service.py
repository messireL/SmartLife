from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import get_app_timezone, format_local_date
from app.db.models import AppSetting, ProviderType
from app.services.tariff_service import get_tariff_display, get_tariff_windows

RUNTIME_KEY_PROVIDER = "provider"
RUNTIME_KEY_TUYA_BASE_URL = "tuya.base_url"
RUNTIME_KEY_TUYA_ACCESS_ID = "tuya.access_id"
RUNTIME_KEY_TUYA_ACCESS_SECRET = "tuya.access_secret"
RUNTIME_KEY_TUYA_PROJECT_CODE = "tuya.project_code"
RUNTIME_KEY_TUYA_API_MODE = "tuya.api_mode"
RUNTIME_KEY_TUYA_FULL_SYNC_INTERVAL_MINUTES = "tuya.full_sync_interval_minutes"
RUNTIME_KEY_TUYA_SPEC_CACHE_HOURS = "tuya.spec_cache_hours"
RUNTIME_KEY_TUYA_LAST_FULL_SYNC_AT = "tuya.last_full_sync_at"

TUYA_API_MODE_STANDARD = "standard"
TUYA_API_MODE_ECONOMY = "economy"

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
RUNTIME_KEY_TARIFF_HISTORY = "tariff.history_json"


@dataclass(slots=True)
class TariffPlan:
    effective_from: str
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
    def effective_from_date(self) -> date:
        return date.fromisoformat(self.effective_from)

    @property
    def tariff_mode_label(self) -> str:
        return {
            "flat": "Единый",
            "two_zone": "Двухзонный",
            "three_zone": "Трёхзонный",
        }.get(self.tariff_mode, "Единый")

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
    def tariff_price_decimal(self) -> Decimal:
        return self.tariff_primary_price_decimal

    @property
    def tariff_display(self) -> str:
        return get_tariff_display(self)

    @property
    def tariff_windows(self) -> list[str]:
        return get_tariff_windows(self)

    @property
    def effective_from_label(self) -> str:
        return format_local_date(self.effective_from_date)

    def to_dict(self) -> dict[str, str]:
        return {
            "effective_from": self.effective_from,
            "tariff_mode": self.tariff_mode,
            "tariff_currency": self.tariff_currency,
            "tariff_flat_price_per_kwh": self.tariff_flat_price_per_kwh,
            "tariff_two_day_price_per_kwh": self.tariff_two_day_price_per_kwh,
            "tariff_two_night_price_per_kwh": self.tariff_two_night_price_per_kwh,
            "tariff_two_day_start": self.tariff_two_day_start,
            "tariff_two_night_start": self.tariff_two_night_start,
            "tariff_three_day_price_per_kwh": self.tariff_three_day_price_per_kwh,
            "tariff_three_night_price_per_kwh": self.tariff_three_night_price_per_kwh,
            "tariff_three_peak_price_per_kwh": self.tariff_three_peak_price_per_kwh,
            "tariff_three_day_start": self.tariff_three_day_start,
            "tariff_three_night_start": self.tariff_three_night_start,
            "tariff_three_peak_morning_start": self.tariff_three_peak_morning_start,
            "tariff_three_peak_morning_end": self.tariff_three_peak_morning_end,
            "tariff_three_peak_evening_start": self.tariff_three_peak_evening_start,
            "tariff_three_peak_evening_end": self.tariff_three_peak_evening_end,
        }


@dataclass(slots=True)
class RuntimeConfig:
    provider: str
    tuya_base_url: str
    tuya_access_id: str
    tuya_access_secret: str
    tuya_project_code: str
    tuya_api_mode: str
    tuya_full_sync_interval_minutes: int
    tuya_spec_cache_hours: int
    tuya_last_full_sync_at: str
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
    tariff_effective_from: str
    tariff_plan_history: tuple[TariffPlan, ...]

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
    def tuya_api_mode_label(self) -> str:
        return "Экономичный" if self.tuya_api_mode == TUYA_API_MODE_ECONOMY else "Стандартный"

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

    @property
    def tariff_effective_from_label(self) -> str:
        return format_local_date(date.fromisoformat(self.tariff_effective_from))


def _get_setting_row(db: Session, key: str) -> AppSetting | None:
    return db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()


def get_setting_value(db: Session, key: str, default: str = "") -> str:
    row = _get_setting_row(db, key)
    if row is None or row.value is None:
        return default
    return str(row.value)


def get_setting_int_value(db: Session, key: str, default: int, *, minimum: int = 1, maximum: int = 1440) -> int:
    raw = get_setting_value(db, key, str(default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


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


def _today_local_date() -> date:
    return datetime.now(get_app_timezone()).date()


def _first_day_of_month(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def get_tariff_change_target_month(today: date | None = None) -> date:
    today = today or _today_local_date()
    current_month = _first_day_of_month(today)
    return current_month if today.day == 1 else _next_month(current_month)


def _plan_from_values(effective_from: date, values: dict[str, str]) -> TariffPlan:
    return TariffPlan(
        effective_from=effective_from.isoformat(),
        tariff_mode=(values.get(RUNTIME_KEY_TARIFF_MODE) or values.get("tariff.mode") or "flat").strip() or "flat",
        tariff_currency=(values.get(RUNTIME_KEY_TARIFF_CURRENCY) or values.get("tariff.currency") or "₽").strip() or "₽",
        tariff_flat_price_per_kwh=(values.get(RUNTIME_KEY_TARIFF_FLAT_PRICE) or values.get("tariff.flat.price_per_kwh") or "0.00").strip() or "0.00",
        tariff_two_day_price_per_kwh=(values.get(RUNTIME_KEY_TARIFF_TWO_DAY_PRICE) or values.get("tariff.two_zone.day_price_per_kwh") or "0.00").strip() or "0.00",
        tariff_two_night_price_per_kwh=(values.get(RUNTIME_KEY_TARIFF_TWO_NIGHT_PRICE) or values.get("tariff.two_zone.night_price_per_kwh") or "0.00").strip() or "0.00",
        tariff_two_day_start=(values.get(RUNTIME_KEY_TARIFF_TWO_DAY_START) or values.get("tariff.two_zone.day_start") or "07:00").strip() or "07:00",
        tariff_two_night_start=(values.get(RUNTIME_KEY_TARIFF_TWO_NIGHT_START) or values.get("tariff.two_zone.night_start") or "23:00").strip() or "23:00",
        tariff_three_day_price_per_kwh=(values.get(RUNTIME_KEY_TARIFF_THREE_DAY_PRICE) or values.get("tariff.three_zone.day_price_per_kwh") or "0.00").strip() or "0.00",
        tariff_three_night_price_per_kwh=(values.get(RUNTIME_KEY_TARIFF_THREE_NIGHT_PRICE) or values.get("tariff.three_zone.night_price_per_kwh") or "0.00").strip() or "0.00",
        tariff_three_peak_price_per_kwh=(values.get(RUNTIME_KEY_TARIFF_THREE_PEAK_PRICE) or values.get("tariff.three_zone.peak_price_per_kwh") or "0.00").strip() or "0.00",
        tariff_three_day_start=(values.get(RUNTIME_KEY_TARIFF_THREE_DAY_START) or values.get("tariff.three_zone.day_start") or "07:00").strip() or "07:00",
        tariff_three_night_start=(values.get(RUNTIME_KEY_TARIFF_THREE_NIGHT_START) or values.get("tariff.three_zone.night_start") or "23:00").strip() or "23:00",
        tariff_three_peak_morning_start=(values.get(RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_START) or values.get("tariff.three_zone.peak_morning_start") or "07:00").strip() or "07:00",
        tariff_three_peak_morning_end=(values.get(RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_END) or values.get("tariff.three_zone.peak_morning_end") or "10:00").strip() or "10:00",
        tariff_three_peak_evening_start=(values.get(RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_START) or values.get("tariff.three_zone.peak_evening_start") or "17:00").strip() or "17:00",
        tariff_three_peak_evening_end=(values.get(RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_END) or values.get("tariff.three_zone.peak_evening_end") or "21:00").strip() or "21:00",
    )


def _read_tariff_history(db: Session) -> list[TariffPlan]:
    raw = get_setting_value(db, RUNTIME_KEY_TARIFF_HISTORY, "")
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        result: list[TariffPlan] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                try:
                    result.append(
                        TariffPlan(
                            effective_from=str(item.get("effective_from") or ""),
                            tariff_mode=str(item.get("tariff_mode") or "flat"),
                            tariff_currency=str(item.get("tariff_currency") or "₽"),
                            tariff_flat_price_per_kwh=str(item.get("tariff_flat_price_per_kwh") or "0.00"),
                            tariff_two_day_price_per_kwh=str(item.get("tariff_two_day_price_per_kwh") or "0.00"),
                            tariff_two_night_price_per_kwh=str(item.get("tariff_two_night_price_per_kwh") or "0.00"),
                            tariff_two_day_start=str(item.get("tariff_two_day_start") or "07:00"),
                            tariff_two_night_start=str(item.get("tariff_two_night_start") or "23:00"),
                            tariff_three_day_price_per_kwh=str(item.get("tariff_three_day_price_per_kwh") or "0.00"),
                            tariff_three_night_price_per_kwh=str(item.get("tariff_three_night_price_per_kwh") or "0.00"),
                            tariff_three_peak_price_per_kwh=str(item.get("tariff_three_peak_price_per_kwh") or "0.00"),
                            tariff_three_day_start=str(item.get("tariff_three_day_start") or "07:00"),
                            tariff_three_night_start=str(item.get("tariff_three_night_start") or "23:00"),
                            tariff_three_peak_morning_start=str(item.get("tariff_three_peak_morning_start") or "07:00"),
                            tariff_three_peak_morning_end=str(item.get("tariff_three_peak_morning_end") or "10:00"),
                            tariff_three_peak_evening_start=str(item.get("tariff_three_peak_evening_start") or "17:00"),
                            tariff_three_peak_evening_end=str(item.get("tariff_three_peak_evening_end") or "21:00"),
                        )
                    )
                except Exception:
                    continue
        result.sort(key=lambda plan: (plan.effective_from, plan.tariff_mode))
        return result
    except Exception:
        return []


def _write_tariff_history(db: Session, plans: list[TariffPlan]) -> None:
    serialized = json.dumps([plan.to_dict() for plan in sorted(plans, key=lambda x: x.effective_from_date)], ensure_ascii=False)
    set_setting_value(db, RUNTIME_KEY_TARIFF_HISTORY, serialized)


def _legacy_tariff_values(db: Session) -> dict[str, str]:
    settings = get_settings()
    legacy_tariff_price = get_setting_value(db, LEGACY_RUNTIME_KEY_TARIFF_PRICE, "0.00")
    return {
        RUNTIME_KEY_TARIFF_MODE: get_setting_value(db, RUNTIME_KEY_TARIFF_MODE, "flat") or "flat",
        RUNTIME_KEY_TARIFF_CURRENCY: get_setting_value(db, RUNTIME_KEY_TARIFF_CURRENCY, "₽") or "₽",
        RUNTIME_KEY_TARIFF_FLAT_PRICE: get_setting_value(db, RUNTIME_KEY_TARIFF_FLAT_PRICE, legacy_tariff_price or "0.00") or "0.00",
        RUNTIME_KEY_TARIFF_TWO_DAY_PRICE: get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_DAY_PRICE, "0.00") or "0.00",
        RUNTIME_KEY_TARIFF_TWO_NIGHT_PRICE: get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_NIGHT_PRICE, "0.00") or "0.00",
        RUNTIME_KEY_TARIFF_TWO_DAY_START: get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_DAY_START, "07:00") or "07:00",
        RUNTIME_KEY_TARIFF_TWO_NIGHT_START: get_setting_value(db, RUNTIME_KEY_TARIFF_TWO_NIGHT_START, "23:00") or "23:00",
        RUNTIME_KEY_TARIFF_THREE_DAY_PRICE: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_DAY_PRICE, "0.00") or "0.00",
        RUNTIME_KEY_TARIFF_THREE_NIGHT_PRICE: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_NIGHT_PRICE, "0.00") or "0.00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_PRICE: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_PRICE, "0.00") or "0.00",
        RUNTIME_KEY_TARIFF_THREE_DAY_START: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_DAY_START, "07:00") or "07:00",
        RUNTIME_KEY_TARIFF_THREE_NIGHT_START: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_NIGHT_START, "23:00") or "23:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_START: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_START, "07:00") or "07:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_END: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_END, "10:00") or "10:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_START: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_START, "17:00") or "17:00",
        RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_END: get_setting_value(db, RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_END, "21:00") or "21:00",
    }


def get_tariff_history(db: Session) -> list[TariffPlan]:
    return _read_tariff_history(db)


def _sync_legacy_tariff_keys(db: Session, plan: TariffPlan) -> bool:
    values = {
        RUNTIME_KEY_TARIFF_MODE: plan.tariff_mode,
        RUNTIME_KEY_TARIFF_CURRENCY: plan.tariff_currency,
        RUNTIME_KEY_TARIFF_FLAT_PRICE: plan.tariff_flat_price_per_kwh,
        RUNTIME_KEY_TARIFF_TWO_DAY_PRICE: plan.tariff_two_day_price_per_kwh,
        RUNTIME_KEY_TARIFF_TWO_NIGHT_PRICE: plan.tariff_two_night_price_per_kwh,
        RUNTIME_KEY_TARIFF_TWO_DAY_START: plan.tariff_two_day_start,
        RUNTIME_KEY_TARIFF_TWO_NIGHT_START: plan.tariff_two_night_start,
        RUNTIME_KEY_TARIFF_THREE_DAY_PRICE: plan.tariff_three_day_price_per_kwh,
        RUNTIME_KEY_TARIFF_THREE_NIGHT_PRICE: plan.tariff_three_night_price_per_kwh,
        RUNTIME_KEY_TARIFF_THREE_PEAK_PRICE: plan.tariff_three_peak_price_per_kwh,
        RUNTIME_KEY_TARIFF_THREE_DAY_START: plan.tariff_three_day_start,
        RUNTIME_KEY_TARIFF_THREE_NIGHT_START: plan.tariff_three_night_start,
        RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_START: plan.tariff_three_peak_morning_start,
        RUNTIME_KEY_TARIFF_THREE_PEAK_MORNING_END: plan.tariff_three_peak_morning_end,
        RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_START: plan.tariff_three_peak_evening_start,
        RUNTIME_KEY_TARIFF_THREE_PEAK_EVENING_END: plan.tariff_three_peak_evening_end,
    }
    changed = False
    for key, value in values.items():
        if get_setting_value(db, key, "") != value:
            set_setting_value(db, key, value)
            changed = True
    return changed


def _select_tariff_plan(local_date: date, plans: list[TariffPlan]) -> TariffPlan | None:
    if not plans:
        return None
    eligible = [plan for plan in plans if plan.effective_from_date <= local_date]
    if eligible:
        return sorted(eligible, key=lambda plan: plan.effective_from_date)[-1]
    return sorted(plans, key=lambda plan: plan.effective_from_date)[0]


def get_tariff_plan_for_date(db: Session, local_date: date | None = None) -> TariffPlan:
    bootstrap_runtime_settings(db)
    local_date = local_date or _today_local_date()
    plans = _read_tariff_history(db)
    selected = _select_tariff_plan(local_date, plans)
    if selected is not None:
        return selected
    return _plan_from_values(_first_day_of_month(local_date), _legacy_tariff_values(db))


def get_next_scheduled_tariff_plan(db: Session, local_date: date | None = None) -> TariffPlan | None:
    bootstrap_runtime_settings(db)
    local_date = local_date or _today_local_date()
    plans = sorted(_read_tariff_history(db), key=lambda plan: plan.effective_from_date)
    current_month = _first_day_of_month(local_date)
    for plan in plans:
        if plan.effective_from_date > current_month:
            return plan
    return None


def get_tariff_editor_plan(db: Session, local_date: date | None = None) -> TariffPlan:
    bootstrap_runtime_settings(db)
    local_date = local_date or _today_local_date()
    target = get_tariff_change_target_month(local_date)
    plans = _read_tariff_history(db)
    for plan in plans:
        if plan.effective_from_date == target:
            return plan
    active_plan = get_tariff_plan_for_date(db, local_date)
    cloned = active_plan.to_dict()
    cloned["effective_from"] = target.isoformat()
    return TariffPlan(**cloned)


def _build_runtime_config(db: Session) -> RuntimeConfig:
    settings = get_settings()
    today = _today_local_date()
    history_list = sorted(_read_tariff_history(db), key=lambda plan: plan.effective_from_date)
    active_plan = _select_tariff_plan(today, history_list)
    if active_plan is None:
        active_plan = _plan_from_values(_first_day_of_month(today), _legacy_tariff_values(db))
        history_list = [active_plan]
    history = tuple(history_list)
    return RuntimeConfig(
        provider=get_setting_value(db, RUNTIME_KEY_PROVIDER, settings.smartlife_provider or ProviderType.DEMO.value),
        tuya_base_url=get_setting_value(db, RUNTIME_KEY_TUYA_BASE_URL, settings.smartlife_tuya_base_url or "https://openapi.tuyaeu.com"),
        tuya_access_id=get_setting_value(db, RUNTIME_KEY_TUYA_ACCESS_ID, settings.smartlife_tuya_access_id or ""),
        tuya_access_secret=get_setting_value(db, RUNTIME_KEY_TUYA_ACCESS_SECRET, settings.smartlife_tuya_access_secret or ""),
        tuya_project_code=get_setting_value(db, RUNTIME_KEY_TUYA_PROJECT_CODE, settings.smartlife_tuya_project_code or ""),
        tuya_api_mode=get_setting_value(db, RUNTIME_KEY_TUYA_API_MODE, TUYA_API_MODE_STANDARD) or TUYA_API_MODE_STANDARD,
        tuya_full_sync_interval_minutes=get_setting_int_value(db, RUNTIME_KEY_TUYA_FULL_SYNC_INTERVAL_MINUTES, 15, minimum=5, maximum=1440),
        tuya_spec_cache_hours=get_setting_int_value(db, RUNTIME_KEY_TUYA_SPEC_CACHE_HOURS, 24, minimum=1, maximum=720),
        tuya_last_full_sync_at=get_setting_value(db, RUNTIME_KEY_TUYA_LAST_FULL_SYNC_AT, ""),
        tariff_mode=active_plan.tariff_mode,
        tariff_currency=active_plan.tariff_currency,
        tariff_flat_price_per_kwh=active_plan.tariff_flat_price_per_kwh,
        tariff_two_day_price_per_kwh=active_plan.tariff_two_day_price_per_kwh,
        tariff_two_night_price_per_kwh=active_plan.tariff_two_night_price_per_kwh,
        tariff_two_day_start=active_plan.tariff_two_day_start,
        tariff_two_night_start=active_plan.tariff_two_night_start,
        tariff_three_day_price_per_kwh=active_plan.tariff_three_day_price_per_kwh,
        tariff_three_night_price_per_kwh=active_plan.tariff_three_night_price_per_kwh,
        tariff_three_peak_price_per_kwh=active_plan.tariff_three_peak_price_per_kwh,
        tariff_three_day_start=active_plan.tariff_three_day_start,
        tariff_three_night_start=active_plan.tariff_three_night_start,
        tariff_three_peak_morning_start=active_plan.tariff_three_peak_morning_start,
        tariff_three_peak_morning_end=active_plan.tariff_three_peak_morning_end,
        tariff_three_peak_evening_start=active_plan.tariff_three_peak_evening_start,
        tariff_three_peak_evening_end=active_plan.tariff_three_peak_evening_end,
        tariff_effective_from=active_plan.effective_from,
        tariff_plan_history=history,
    )


def bootstrap_runtime_settings(db: Session) -> RuntimeConfig:
    settings = get_settings()
    defaults = {
        RUNTIME_KEY_PROVIDER: settings.smartlife_provider or ProviderType.DEMO.value,
        RUNTIME_KEY_TUYA_BASE_URL: settings.smartlife_tuya_base_url or "https://openapi.tuyaeu.com",
        RUNTIME_KEY_TUYA_ACCESS_ID: settings.smartlife_tuya_access_id or "",
        RUNTIME_KEY_TUYA_ACCESS_SECRET: settings.smartlife_tuya_access_secret or "",
        RUNTIME_KEY_TUYA_PROJECT_CODE: settings.smartlife_tuya_project_code or "",
        RUNTIME_KEY_TUYA_API_MODE: TUYA_API_MODE_STANDARD,
        RUNTIME_KEY_TUYA_FULL_SYNC_INTERVAL_MINUTES: "15",
        RUNTIME_KEY_TUYA_SPEC_CACHE_HOURS: "24",
        RUNTIME_KEY_TUYA_LAST_FULL_SYNC_AT: "",
    }
    changed = False
    for key, default_value in defaults.items():
        row = _get_setting_row(db, key)
        if row is None:
            db.add(AppSetting(key=key, value=default_value))
            changed = True

    plans = _read_tariff_history(db)
    if not plans:
        initial_plan = _plan_from_values(_first_day_of_month(_today_local_date()), _legacy_tariff_values(db))
        plans = [initial_plan]
        _write_tariff_history(db, plans)
        _sync_legacy_tariff_keys(db, initial_plan)
        changed = True
    else:
        active_plan = _select_tariff_plan(_today_local_date(), plans) or plans[0]
        changed = _sync_legacy_tariff_keys(db, active_plan) or changed

    if changed:
        db.commit()
    return _build_runtime_config(db)


def get_runtime_config(db: Session) -> RuntimeConfig:
    return bootstrap_runtime_settings(db)


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


def configure_tuya_api_runtime(db: Session, *, api_mode: str, full_sync_interval_minutes: int, spec_cache_hours: int) -> RuntimeConfig:
    mode = (api_mode or TUYA_API_MODE_STANDARD).strip()
    if mode not in {TUYA_API_MODE_STANDARD, TUYA_API_MODE_ECONOMY}:
        mode = TUYA_API_MODE_STANDARD
    set_runtime_values(
        db,
        {
            RUNTIME_KEY_TUYA_API_MODE: mode,
            RUNTIME_KEY_TUYA_FULL_SYNC_INTERVAL_MINUTES: str(max(5, min(1440, int(full_sync_interval_minutes)))),
            RUNTIME_KEY_TUYA_SPEC_CACHE_HOURS: str(max(1, min(720, int(spec_cache_hours)))),
        },
    )
    return get_runtime_config(db)


def mark_tuya_full_sync_completed(db: Session, *, finished_at: datetime | None = None) -> None:
    timestamp = (finished_at or datetime.utcnow()).replace(microsecond=0).isoformat()
    set_setting_value(db, RUNTIME_KEY_TUYA_LAST_FULL_SYNC_AT, timestamp)


def configure_demo_provider(db: Session) -> RuntimeConfig:
    set_runtime_values(db, {RUNTIME_KEY_PROVIDER: ProviderType.DEMO.value})
    return get_runtime_config(db)


def configure_tariff_settings(db: Session, *, values: dict[str, str], effective_from: date | None = None) -> tuple[RuntimeConfig, TariffPlan]:
    normalized_values = {key: (value or "").strip() for key, value in values.items()}
    effective_from = effective_from or get_tariff_change_target_month()
    plan = _plan_from_values(effective_from, normalized_values)
    plans = _read_tariff_history(db)
    replaced = False
    for index, existing in enumerate(plans):
        if existing.effective_from_date == effective_from:
            plans[index] = plan
            replaced = True
            break
    if not replaced:
        plans.append(plan)
    plans = sorted(plans, key=lambda item: item.effective_from_date)
    _write_tariff_history(db, plans)
    active_plan = get_tariff_plan_for_date(db, _today_local_date()) if plans else plan
    _sync_legacy_tariff_keys(db, active_plan)
    db.commit()
    return get_runtime_config(db), plan
