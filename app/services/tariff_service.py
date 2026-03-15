from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import get_app_timezone, to_local
from app.db.models import DeviceStatusSnapshot

ZERO = Decimal("0.000")
MONEY_ZERO = Decimal("0.00")


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



def calculate_tariff_costs(db: Session, runtime, *, device_ids: list[int] | None = None) -> dict:
    tz = get_app_timezone()
    today = datetime.now(tz).date()
    month_start = today.replace(day=1)
    query_start = _period_start_utc_naive(month_start, tz) - timedelta(days=2)

    stmt = (
        select(DeviceStatusSnapshot.device_id, DeviceStatusSnapshot.recorded_at, DeviceStatusSnapshot.energy_total_kwh)
        .where(DeviceStatusSnapshot.recorded_at >= query_start, DeviceStatusSnapshot.energy_total_kwh.is_not(None))
        .order_by(DeviceStatusSnapshot.device_id.asc(), DeviceStatusSnapshot.recorded_at.asc(), DeviceStatusSnapshot.id.asc())
    )
    if device_ids:
        stmt = stmt.where(DeviceStatusSnapshot.device_id.in_(device_ids))

    rows = db.execute(stmt).all()
    today_plan = get_tariff_plan_for_local_date(runtime, today)
    month_plan = get_tariff_plan_for_local_date(runtime, month_start)

    def fresh_buckets(plan) -> dict[str, ZoneBucket]:
        return {item.key: ZoneBucket(key=item.key, label=item.label, rate=item.rate) for item in get_tariff_zone_definitions(plan)}

    today_buckets = fresh_buckets(today_plan)
    month_buckets = fresh_buckets(month_plan)
    per_device: dict[int, dict] = {}
    previous: dict[int, tuple[datetime, Decimal]] = {}

    for device_id, recorded_at, energy_total_kwh in rows:
        current_total = _quantize_energy(energy_total_kwh)
        prev = previous.get(device_id)
        previous[device_id] = (recorded_at, current_total)
        if prev is None:
            continue
        _prev_dt, prev_total = prev
        delta = _quantize_energy(current_total - prev_total)
        if delta <= ZERO:
            continue
        local_dt = to_local(recorded_at)
        if local_dt is None:
            continue
        plan = get_tariff_plan_for_local_date(runtime, local_dt.date())
        if device_id not in per_device:
            per_device[device_id] = {
                "today_cost": MONEY_ZERO,
                "month_cost": MONEY_ZERO,
                "today_energy_kwh": ZERO,
                "month_energy_kwh": ZERO,
                "today_zones": fresh_buckets(today_plan),
                "month_zones": fresh_buckets(month_plan),
            }
        zone_key = get_tariff_zone_for_local_datetime(plan, local_dt)
        rate = get_tariff_rate_for_zone(plan, zone_key)
        cost = _quantize_money(delta * rate)
        if local_dt.date() >= month_start:
            if zone_key not in month_buckets:
                month_buckets[zone_key] = ZoneBucket(key=zone_key, label=zone_key, rate=rate)
                per_device[device_id]["month_zones"][zone_key] = ZoneBucket(key=zone_key, label=zone_key, rate=rate)
            month_buckets[zone_key].energy_kwh += delta
            month_buckets[zone_key].cost += cost
            per_device[device_id]["month_cost"] += cost
            per_device[device_id]["month_energy_kwh"] += delta
            per_device[device_id]["month_zones"][zone_key].energy_kwh += delta
            per_device[device_id]["month_zones"][zone_key].cost += cost
        if local_dt.date() == today:
            if zone_key not in today_buckets:
                today_buckets[zone_key] = ZoneBucket(key=zone_key, label=zone_key, rate=rate)
                per_device[device_id]["today_zones"][zone_key] = ZoneBucket(key=zone_key, label=zone_key, rate=rate)
            today_buckets[zone_key].energy_kwh += delta
            today_buckets[zone_key].cost += cost
            per_device[device_id]["today_cost"] += cost
            per_device[device_id]["today_energy_kwh"] += delta
            per_device[device_id]["today_zones"][zone_key].energy_kwh += delta
            per_device[device_id]["today_zones"][zone_key].cost += cost

    def bucket_list(buckets: dict[str, ZoneBucket], mode: str) -> list[dict]:
        return [
            {
                "key": bucket.key,
                "label": bucket.label,
                "rate": _quantize_money(bucket.rate),
                "energy_kwh": _quantize_energy(bucket.energy_kwh),
                "cost": _quantize_money(bucket.cost),
            }
            for bucket in buckets.values()
            if bucket.energy_kwh > ZERO or mode == "flat"
        ]

    for device_data in per_device.values():
        device_data["today_cost"] = _quantize_money(device_data["today_cost"])
        device_data["month_cost"] = _quantize_money(device_data["month_cost"])
        device_data["today_energy_kwh"] = _quantize_energy(device_data["today_energy_kwh"])
        device_data["month_energy_kwh"] = _quantize_energy(device_data["month_energy_kwh"])
        device_data["today_zones_list"] = bucket_list(device_data["today_zones"], getattr(today_plan, "tariff_mode", "flat"))
        device_data["month_zones_list"] = bucket_list(device_data["month_zones"], getattr(month_plan, "tariff_mode", "flat"))

    return {
        "today_total_cost": _quantize_money(sum((bucket.cost for bucket in today_buckets.values()), MONEY_ZERO)),
        "month_total_cost": _quantize_money(sum((bucket.cost for bucket in month_buckets.values()), MONEY_ZERO)),
        "today_zones": bucket_list(today_buckets, getattr(today_plan, "tariff_mode", "flat")),
        "month_zones": bucket_list(month_buckets, getattr(month_plan, "tariff_mode", "flat")),
        "per_device": per_device,
        "mode_label": _mode_label(getattr(today_plan, "tariff_mode", "flat")),
    }
