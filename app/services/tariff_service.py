from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import get_app_timezone, to_local
from app.services.telemetry_energy_service import estimate_energy_delta
from app.db.models import DeviceStatusSnapshot

ZERO = Decimal("0.000")
MONEY_ZERO = Decimal("0.00")
ZONE_ORDER = {"flat": 0, "day": 1, "night": 2, "peak": 3}


@dataclass(slots=True)
class ZoneBucket:
    key: str
    label: str
    rate: Decimal
    energy_kwh: Decimal = ZERO
    cost: Decimal = MONEY_ZERO



def _quantize_energy(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return value.quantize(Decimal("0.000"))



def _quantize_money(value: Decimal | None) -> Decimal:
    if value is None:
        return MONEY_ZERO
    return value.quantize(Decimal("0.00"))



def _parse_time(value: str | None, default: str) -> time:
    raw = (value or "").strip() or default
    try:
        hour_str, minute_str = raw.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError
        return time(hour=hour, minute=minute)
    except Exception:
        return _parse_time(default, default) if raw != default else time(0, 0)



def _parse_decimal(value: str | None, default: str = "0.00") -> Decimal:
    raw = (value or "").strip().replace(",", ".") or default
    try:
        parsed = Decimal(raw)
        if parsed < 0:
            return Decimal(default)
        return parsed.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal(default)



def _time_in_range(moment: time, start: time, end: time) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end



def _mode_label(mode: str) -> str:
    return {
        "flat": "Единый",
        "two_zone": "Двухзонный",
        "three_zone": "Трёхзонный",
    }.get(mode, "Единый")



def get_tariff_zone_definitions(runtime) -> list[ZoneBucket]:
    mode = getattr(runtime, "tariff_mode", "flat")
    if mode == "two_zone":
        return [
            ZoneBucket(key="day", label="День", rate=_parse_decimal(getattr(runtime, "tariff_two_day_price_per_kwh", "0.00"))),
            ZoneBucket(key="night", label="Ночь", rate=_parse_decimal(getattr(runtime, "tariff_two_night_price_per_kwh", "0.00"))),
        ]
    if mode == "three_zone":
        return [
            ZoneBucket(key="day", label="День", rate=_parse_decimal(getattr(runtime, "tariff_three_day_price_per_kwh", "0.00"))),
            ZoneBucket(key="night", label="Ночь", rate=_parse_decimal(getattr(runtime, "tariff_three_night_price_per_kwh", "0.00"))),
            ZoneBucket(key="peak", label="Пик", rate=_parse_decimal(getattr(runtime, "tariff_three_peak_price_per_kwh", "0.00"))),
        ]
    return [ZoneBucket(key="flat", label="Единый", rate=_parse_decimal(getattr(runtime, "tariff_flat_price_per_kwh", "0.00")))]



def get_tariff_zone_for_local_datetime(runtime, dt_local: datetime) -> str:
    mode = getattr(runtime, "tariff_mode", "flat")
    moment = dt_local.timetz().replace(tzinfo=None)
    if mode == "two_zone":
        day_start = _parse_time(getattr(runtime, "tariff_two_day_start", "07:00"), "07:00")
        night_start = _parse_time(getattr(runtime, "tariff_two_night_start", "23:00"), "23:00")
        return "day" if _time_in_range(moment, day_start, night_start) else "night"
    if mode == "three_zone":
        night_start = _parse_time(getattr(runtime, "tariff_three_night_start", "23:00"), "23:00")
        day_start = _parse_time(getattr(runtime, "tariff_three_day_start", "07:00"), "07:00")
        peak_morning_start = _parse_time(getattr(runtime, "tariff_three_peak_morning_start", "07:00"), "07:00")
        peak_morning_end = _parse_time(getattr(runtime, "tariff_three_peak_morning_end", "10:00"), "10:00")
        peak_evening_start = _parse_time(getattr(runtime, "tariff_three_peak_evening_start", "17:00"), "17:00")
        peak_evening_end = _parse_time(getattr(runtime, "tariff_three_peak_evening_end", "21:00"), "21:00")
        if not _time_in_range(moment, day_start, night_start):
            return "night"
        if _time_in_range(moment, peak_morning_start, peak_morning_end) or _time_in_range(moment, peak_evening_start, peak_evening_end):
            return "peak"
        return "day"
    return "flat"



def _get_tariff_plan_history(runtime) -> list[object]:
    history = getattr(runtime, "tariff_plan_history", None)
    if history:
        try:
            return sorted(list(history), key=lambda item: getattr(item, "effective_from_date", date.min))
        except Exception:
            return list(history)
    return [runtime]



def get_tariff_plan_for_local_date(runtime, local_date: date):
    history = _get_tariff_plan_history(runtime)
    eligible = []
    for plan in history:
        effective_from = getattr(plan, "effective_from_date", None)
        if effective_from is None or effective_from <= local_date:
            eligible.append(plan)
    if eligible:
        return sorted(eligible, key=lambda item: getattr(item, "effective_from_date", date.min))[-1]
    return history[0]



def get_tariff_rate_for_zone(runtime, zone_key: str) -> Decimal:
    for zone in get_tariff_zone_definitions(runtime):
        if zone.key == zone_key:
            return zone.rate
    return Decimal("0.00")



def get_tariff_display(runtime) -> str:
    mode = getattr(runtime, "tariff_mode", "flat")
    currency = (getattr(runtime, "tariff_currency", "₽") or "₽").strip() or "₽"
    zones = get_tariff_zone_definitions(runtime)
    if mode == "flat":
        zone = zones[0]
        return f"{zone.rate:.2f} {currency}/kWh"
    if mode == "two_zone":
        parts = [f"День {zones[0].rate:.2f}", f"Ночь {zones[1].rate:.2f}"]
        return f"Двухзонный · {' · '.join(parts)} {currency}/kWh"
    lookup = {zone.key: zone for zone in zones}
    return (
        f"Трёхзонный · День {lookup['day'].rate:.2f} · Ночь {lookup['night'].rate:.2f} · Пик {lookup['peak'].rate:.2f} {currency}/kWh"
    )



def get_tariff_windows(runtime) -> list[str]:
    mode = getattr(runtime, "tariff_mode", "flat")
    if mode == "two_zone":
        return [
            f"День: {getattr(runtime, 'tariff_two_day_start', '07:00')}–{getattr(runtime, 'tariff_two_night_start', '23:00')}",
            f"Ночь: {getattr(runtime, 'tariff_two_night_start', '23:00')}–{getattr(runtime, 'tariff_two_day_start', '07:00')}",
        ]
    if mode == "three_zone":
        return [
            f"Ночь: {getattr(runtime, 'tariff_three_night_start', '23:00')}–{getattr(runtime, 'tariff_three_day_start', '07:00')}",
            f"Пик 1: {getattr(runtime, 'tariff_three_peak_morning_start', '07:00')}–{getattr(runtime, 'tariff_three_peak_morning_end', '10:00')}",
            f"День: {getattr(runtime, 'tariff_three_day_start', '07:00')}–{getattr(runtime, 'tariff_three_night_start', '23:00')} кроме пиков",
            f"Пик 2: {getattr(runtime, 'tariff_three_peak_evening_start', '17:00')}–{getattr(runtime, 'tariff_three_peak_evening_end', '21:00')}",
        ]
    return ["Единый тариф на весь день"]



def _period_start_utc_naive(local_date_value: date, tz: ZoneInfo) -> datetime:
    local_dt = datetime.combine(local_date_value, time(0, 0), tzinfo=tz)
    return local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)



def _zone_meta(plan) -> dict[str, tuple[str, Decimal]]:
    return {item.key: (item.label, item.rate) for item in get_tariff_zone_definitions(plan)}



def _new_zone_aggregate(key: str, label: str) -> dict:
    return {"key": key, "label": label, "energy_kwh": ZERO, "cost": MONEY_ZERO, "rates": set()}



def _bucket_list(buckets: dict[str, dict], default_mode: str) -> list[dict]:
    result: list[dict] = []
    for bucket in sorted(buckets.values(), key=lambda item: (ZONE_ORDER.get(item["key"], 99), item["label"])):
        energy = _quantize_energy(bucket["energy_kwh"])
        cost = _quantize_money(bucket["cost"])
        if energy <= ZERO and default_mode != "flat" and bucket["key"] != "flat":
            continue
        rates = sorted(bucket["rates"])
        result.append(
            {
                "key": bucket["key"],
                "label": bucket["label"],
                "rate": _quantize_money(rates[0]) if len(rates) == 1 else None,
                "mixed_rate": len(rates) > 1,
                "energy_kwh": energy,
                "cost": cost,
            }
        )
    return result



def calculate_tariff_costs(db: Session, runtime, *, device_ids: list[int] | None = None, runtime_by_device_id: dict[int, object] | None = None) -> dict:
    tz = get_app_timezone()
    today = datetime.now(tz).date()
    month_start = today.replace(day=1)
    query_start = _period_start_utc_naive(month_start, tz) - timedelta(days=2)

    stmt = (
        select(
            DeviceStatusSnapshot.device_id,
            DeviceStatusSnapshot.recorded_at,
            DeviceStatusSnapshot.energy_total_kwh,
            DeviceStatusSnapshot.power_w,
        )
        .where(
            DeviceStatusSnapshot.recorded_at >= query_start,
            (DeviceStatusSnapshot.energy_total_kwh.is_not(None) | DeviceStatusSnapshot.power_w.is_not(None)),
        )
        .order_by(DeviceStatusSnapshot.device_id.asc(), DeviceStatusSnapshot.recorded_at.asc(), DeviceStatusSnapshot.id.asc())
    )
    if device_ids:
        stmt = stmt.where(DeviceStatusSnapshot.device_id.in_(device_ids))

    rows = db.execute(stmt).all()
    default_today_plan = get_tariff_plan_for_local_date(runtime, today)
    default_month_plan = get_tariff_plan_for_local_date(runtime, month_start)

    today_buckets: dict[str, dict] = {
        item.key: _new_zone_aggregate(item.key, item.label) for item in get_tariff_zone_definitions(default_today_plan)
    }
    month_buckets: dict[str, dict] = {
        item.key: _new_zone_aggregate(item.key, item.label) for item in get_tariff_zone_definitions(default_month_plan)
    }
    per_device: dict[int, dict] = {}
    previous: dict[int, tuple[datetime, Decimal | None, Decimal | None]] = {}
    mode_set: set[str] = set()
    currency_set: set[str] = set()

    for device_id, recorded_at, energy_total_kwh, power_w in rows:
        current_total = _quantize_energy(energy_total_kwh) if energy_total_kwh is not None else None
        prev = previous.get(device_id)
        previous[device_id] = (recorded_at, current_total, power_w)
        if prev is None:
            continue
        prev_dt, prev_total, prev_power = prev
        telemetry_delta = estimate_energy_delta(
            previous_recorded_at=prev_dt,
            previous_energy_total_kwh=prev_total,
            previous_power_w=prev_power,
            current_recorded_at=recorded_at,
            current_energy_total_kwh=current_total,
            current_power_w=power_w,
        )
        if telemetry_delta is None:
            continue
        delta = _quantize_energy(telemetry_delta.delta_kwh)
        if delta <= ZERO:
            continue
        local_dt = to_local(recorded_at)
        if local_dt is None:
            continue

        active_runtime = (runtime_by_device_id or {}).get(device_id, runtime)
        today_plan = get_tariff_plan_for_local_date(active_runtime, today)
        month_plan = get_tariff_plan_for_local_date(active_runtime, month_start)
        plan = get_tariff_plan_for_local_date(active_runtime, local_dt.date())
        mode_set.add(getattr(active_runtime, "tariff_mode", "flat"))
        currency_set.add((getattr(active_runtime, "tariff_currency", "₽") or "₽").strip() or "₽")

        if device_id not in per_device:
            per_device[device_id] = {
                "today_cost": MONEY_ZERO,
                "month_cost": MONEY_ZERO,
                "today_energy_kwh": ZERO,
                "month_energy_kwh": ZERO,
                "today_zones": {item.key: _new_zone_aggregate(item.key, item.label) for item in get_tariff_zone_definitions(today_plan)},
                "month_zones": {item.key: _new_zone_aggregate(item.key, item.label) for item in get_tariff_zone_definitions(month_plan)},
                "tariff_mode": getattr(active_runtime, "tariff_mode", "flat"),
                "tariff_currency": (getattr(active_runtime, "tariff_currency", "₽") or "₽").strip() or "₽",
            }

        zone_key = get_tariff_zone_for_local_datetime(plan, local_dt)
        zone_meta = _zone_meta(plan)
        zone_label, zone_rate = zone_meta.get(zone_key, (zone_key, get_tariff_rate_for_zone(plan, zone_key)))
        cost = _quantize_money(delta * zone_rate)

        if local_dt.date() >= month_start:
            month_bucket = month_buckets.setdefault(zone_key, _new_zone_aggregate(zone_key, zone_label))
            month_bucket["label"] = zone_label
            month_bucket["energy_kwh"] += delta
            month_bucket["cost"] += cost
            month_bucket["rates"].add(zone_rate)

            device_bucket = per_device[device_id]["month_zones"].setdefault(zone_key, _new_zone_aggregate(zone_key, zone_label))
            device_bucket["label"] = zone_label
            device_bucket["energy_kwh"] += delta
            device_bucket["cost"] += cost
            device_bucket["rates"].add(zone_rate)
            per_device[device_id]["month_cost"] += cost
            per_device[device_id]["month_energy_kwh"] += delta

        if local_dt.date() == today:
            today_bucket = today_buckets.setdefault(zone_key, _new_zone_aggregate(zone_key, zone_label))
            today_bucket["label"] = zone_label
            today_bucket["energy_kwh"] += delta
            today_bucket["cost"] += cost
            today_bucket["rates"].add(zone_rate)

            device_bucket = per_device[device_id]["today_zones"].setdefault(zone_key, _new_zone_aggregate(zone_key, zone_label))
            device_bucket["label"] = zone_label
            device_bucket["energy_kwh"] += delta
            device_bucket["cost"] += cost
            device_bucket["rates"].add(zone_rate)
            per_device[device_id]["today_cost"] += cost
            per_device[device_id]["today_energy_kwh"] += delta

    for device_data in per_device.values():
        device_data["today_cost"] = _quantize_money(device_data["today_cost"])
        device_data["month_cost"] = _quantize_money(device_data["month_cost"])
        device_data["today_energy_kwh"] = _quantize_energy(device_data["today_energy_kwh"])
        device_data["month_energy_kwh"] = _quantize_energy(device_data["month_energy_kwh"])
        device_data["today_zones_list"] = _bucket_list(device_data["today_zones"], device_data["tariff_mode"])
        device_data["month_zones_list"] = _bucket_list(device_data["month_zones"], device_data["tariff_mode"])

    mixed_modes = len(mode_set) > 1
    mixed_currency = len(currency_set) > 1
    primary_currency = next(iter(currency_set), (getattr(runtime, "tariff_currency", "₽") or "₽").strip() or "₽")

    return {
        "today_total_cost": _quantize_money(sum((bucket["cost"] for bucket in today_buckets.values()), MONEY_ZERO)),
        "month_total_cost": _quantize_money(sum((bucket["cost"] for bucket in month_buckets.values()), MONEY_ZERO)),
        "today_zones": _bucket_list(today_buckets, getattr(default_today_plan, "tariff_mode", "flat")),
        "month_zones": _bucket_list(month_buckets, getattr(default_month_plan, "tariff_mode", "flat")),
        "per_device": per_device,
        "mode_label": "Смешанный" if mixed_modes else _mode_label(getattr(default_today_plan, "tariff_mode", "flat")),
        "mixed_modes": mixed_modes,
        "mixed_currency": mixed_currency,
        "tariff_currency": primary_currency,
    }
