from __future__ import annotations

from datetime import timedelta
import json
import re
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import format_local_date, format_local_datetime, local_today
from app.db.models import BucketType, Device, DeviceStatusSnapshot, EnergySample, SyncRun, SyncRunStatus
from app.services.chart_service import build_bar_chart, build_line_chart
from app.services.runtime_config_service import get_runtime_config
from app.services.sync_runner import is_sync_running
from app.services.tariff_service import calculate_tariff_costs

ZERO = Decimal("0.000")


def _quantize(value: Decimal | None, places: str = "0.00") -> Decimal:
    if value is None:
        return Decimal(places)
    return value.quantize(Decimal(places))



def _money(value: Decimal | None) -> Decimal:
    return _quantize(value, "0.00")



def _visible_device_ids(db: Session) -> list[int]:
    return list(
        db.scalars(select(Device.id).where(Device.is_hidden.is_(False), Device.is_deleted.is_(False))).all()
    )



def _label_mode(value: str | None) -> str | None:
    if not value:
        return None
    mapping = {
        'turbo': 'Turbo',
        'eco': 'Eco',
        'auto': 'Auto',
        'smart': 'Smart',
        'manual': 'Ручной',
        'heat': 'Heat',
    }
    return mapping.get(value, value)



def _profile_label(value: str | None) -> str | None:
    if value == 'boiler':
        return 'Бойлер'
    if value == 'temperature':
        return 'Температурное устройство'
    if value == 'power_strip':
        return 'Сетевой фильтр / удлинитель'
    return None


def _rate_label(value: Decimal | None, currency: str) -> str:
    rate = _money(value)
    return f"{rate} {currency}/kWh"


def _zone_breakdown(items: list[dict], currency: str) -> list[dict]:
    breakdown: list[dict] = []
    for item in items or []:
        breakdown.append(
            {
                "label": str(item.get("label") or "Зона"),
                "rate": _rate_label(item.get("rate"), currency),
                "energy_display": f"{item.get('energy_kwh', Decimal('0.000'))} kWh",
                "cost_display": f"{_money(item.get('cost'))} {currency}",
            }
        )
    return breakdown



def get_dashboard_summary(db: Session) -> dict:
    today = local_today()
    month_start = today.replace(day=1)
    runtime = get_runtime_config(db)

    devices_total = db.scalar(select(func.count()).select_from(Device).where(Device.is_hidden.is_(False), Device.is_deleted.is_(False))) or 0
    online_total = db.scalar(select(func.count()).select_from(Device).where(Device.is_hidden.is_(False), Device.is_deleted.is_(False), Device.is_online.is_(True))) or 0
    powered_on_total = db.scalar(select(func.count()).select_from(Device).where(Device.is_hidden.is_(False), Device.is_deleted.is_(False), Device.switch_on.is_(True))) or 0

    day_total = db.scalar(
        select(func.coalesce(func.sum(EnergySample.energy_kwh), ZERO))
        .join(Device, Device.id == EnergySample.device_id)
        .where(
            Device.is_hidden.is_(False), Device.is_deleted.is_(False),
            EnergySample.bucket_type == BucketType.DAY,
            EnergySample.period_start == today,
        )
    ) or ZERO

    month_total = db.scalar(
        select(func.coalesce(func.sum(EnergySample.energy_kwh), ZERO))
        .join(Device, Device.id == EnergySample.device_id)
        .where(
            Device.is_hidden.is_(False), Device.is_deleted.is_(False),
            EnergySample.bucket_type == BucketType.MONTH,
            EnergySample.period_start == month_start,
        )
    ) or ZERO

    live_power_total = db.scalar(
        select(func.coalesce(func.sum(Device.current_power_w), Decimal("0.00"))).where(
            Device.is_hidden.is_(False), Device.is_deleted.is_(False), Device.current_power_w.is_not(None)
        )
    ) or Decimal("0.00")

    power_now_total = db.scalar(
        select(func.count()).select_from(Device).where(
            Device.is_hidden.is_(False), Device.is_deleted.is_(False), Device.current_power_w.is_not(None), Device.current_power_w > 0
        )
    ) or 0

    tariff_costs = calculate_tariff_costs(db, runtime, device_ids=_visible_device_ids(db))

    day_total_cost = _money(tariff_costs["today_total_cost"])
    month_total_cost = _money(tariff_costs["month_total_cost"])
    day_zone_costs = tariff_costs["today_zones"]
    month_zone_costs = tariff_costs["month_zones"]

    return {
        "devices_total": devices_total,
        "online_total": online_total,
        "powered_on_total": powered_on_total,
        "day_total_kwh": _quantize(day_total, "0.000"),
        "month_total_kwh": _quantize(month_total, "0.000"),
        "day_total_cost": day_total_cost,
        "month_total_cost": month_total_cost,
        "day_zone_costs": day_zone_costs,
        "month_zone_costs": month_zone_costs,
        "day_breakdown": _zone_breakdown(day_zone_costs, runtime.tariff_currency),
        "month_breakdown": _zone_breakdown(month_zone_costs, runtime.tariff_currency),
        "tariff_price_per_kwh": runtime.tariff_primary_price_decimal,
        "tariff_currency": runtime.tariff_currency,
        "tariff_display": runtime.tariff_display,
        "tariff_mode": runtime.tariff_mode,
        "tariff_mode_label": runtime.tariff_mode_label,
        "tariff_windows": runtime.tariff_windows,
        "live_power_total_w": _quantize(live_power_total),
        "power_now_total": power_now_total,
    }



def get_sync_overview(db: Session) -> dict:
    settings = get_settings()
    last_run = db.execute(select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(1)).scalar_one_or_none()
    success_total = db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.status == SyncRunStatus.SUCCESS)) or 0
    error_total = db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.status == SyncRunStatus.ERROR)) or 0
    return {
        "background_sync_enabled": settings.smartlife_background_sync_enabled,
        "sync_on_startup": settings.smartlife_sync_on_startup,
        "sync_interval_seconds": settings.smartlife_sync_interval_seconds,
        "is_running_now": is_sync_running(),
        "last_run": last_run,
        "success_total": success_total,
        "error_total": error_total,
    }



def get_dashboard_panels(db: Session) -> dict:
    today = local_today()
    runtime = get_runtime_config(db)
    month_start = today.replace(day=1)
    trend_start = today - timedelta(days=13)

    day_rows = db.execute(
        select(EnergySample.period_start, func.coalesce(func.sum(EnergySample.energy_kwh), ZERO))
        .join(Device, Device.id == EnergySample.device_id)
        .where(
            Device.is_hidden.is_(False), Device.is_deleted.is_(False),
            EnergySample.bucket_type == BucketType.DAY,
            EnergySample.period_start >= trend_start,
            EnergySample.period_start <= today,
        )
        .group_by(EnergySample.period_start)
        .order_by(EnergySample.period_start.asc())
    ).all()
    day_map = {row[0]: row[1] for row in day_rows}
    trend_items: list[dict] = []
    for offset in range(14):
        period = trend_start + timedelta(days=offset)
        value = day_map.get(period, ZERO)
        trend_items.append(
            {
                "label": format_local_date(period, "%d-%m"),
                "value": value,
                "value_display": f"{value:.3f} kWh",
                "title": f"{format_local_date(period)} — {value:.3f} kWh",
            }
        )

    live_now = db.execute(
        select(Device)
        .where(Device.is_hidden.is_(False), Device.is_deleted.is_(False), Device.current_power_w.is_not(None), Device.current_power_w > 0)
        .order_by(Device.current_power_w.desc(), Device.name.asc())
        .limit(8)
    ).scalars().all()

    top_today_rows = db.execute(
        select(Device, EnergySample.energy_kwh)
        .join(EnergySample, EnergySample.device_id == Device.id)
        .where(
            Device.is_hidden.is_(False), Device.is_deleted.is_(False),
            EnergySample.bucket_type == BucketType.DAY,
            EnergySample.period_start == today,
            EnergySample.energy_kwh > 0,
        )
        .order_by(EnergySample.energy_kwh.desc(), Device.name.asc())
        .limit(8)
    ).all()

    top_month_rows = db.execute(
        select(Device, EnergySample.energy_kwh)
        .join(EnergySample, EnergySample.device_id == Device.id)
        .where(
            Device.is_hidden.is_(False), Device.is_deleted.is_(False),
            EnergySample.bucket_type == BucketType.MONTH,
            EnergySample.period_start == month_start,
            EnergySample.energy_kwh > 0,
        )
        .order_by(EnergySample.energy_kwh.desc(), Device.name.asc())
        .limit(8)
    ).all()

    cost_data = calculate_tariff_costs(db, runtime, device_ids=_visible_device_ids(db))

    current_power_chart = build_bar_chart(
        [
            {
                "label": (device.display_name[:14] + "…") if len(device.display_name) > 15 else device.display_name,
                "value": device.current_power_w,
                "value_display": f"{_quantize(device.current_power_w)} W",
                "title": f"{device.display_name} — {_quantize(device.current_power_w)} W",
            }
            for device in live_now
        ],
        suffix=" W",
    )

    top_today_chart = build_bar_chart(
        [
            {
                "label": (device.display_name[:14] + "…") if len(device.display_name) > 15 else device.display_name,
                "value": energy,
                "value_display": f"{energy:.3f} kWh",
                "title": f"{device.display_name} — {energy:.3f} kWh",
            }
            for device, energy in top_today_rows
        ],
        suffix=" kWh",
    )

    top_cost_today_rows = [
        {
            "device": device,
            "energy_kwh": energy,
            "cost": _money(cost_data.get(device.id, {}).get("today_cost", Decimal("0.00"))),
        }
        for device, energy in top_today_rows
    ]
    top_cost_month_rows = [
        {
            "device": device,
            "energy_kwh": energy,
            "cost": _money(cost_data.get(device.id, {}).get("month_cost", Decimal("0.00"))),
        }
        for device, energy in top_month_rows
    ]

    return {
        "daily_totals_chart": build_bar_chart(trend_items, suffix=" kWh"),
        "current_power_chart": current_power_chart,
        "top_today_chart": top_today_chart,
        "live_now": live_now,
        "top_today": top_cost_today_rows,
        "top_month": top_cost_month_rows,
        "tariff_display": runtime.tariff_display,
        "tariff_mode_label": runtime.tariff_mode_label,
        "tariff_windows": runtime.tariff_windows,
        "tariff_currency": runtime.tariff_currency,
        "trend_period_label": f"{format_local_date(trend_start)} — {format_local_date(today)}",
    }





def _switch_code_sort_key(code: str) -> tuple[int, int, str]:
    if code == "switch":
        return (0, 0, code)
    socket_match = re.fullmatch(r"switch_(\d+)", code or "")
    if socket_match:
        return (1, int(socket_match.group(1)), code)
    if code == "switch_usb":
        return (2, 0, code)
    usb_match = re.fullmatch(r"switch_usb(\d+)", code or "")
    if usb_match:
        return (2, int(usb_match.group(1)), code)
    return (9, 0, code or "")


def _load_status_payload(raw_payload: str | None) -> dict[str, object]:
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_status_payload(raw_payload: str | None) -> tuple[dict[str, object], set[str], dict[str, object]]:
    payload = _load_status_payload(raw_payload)
    statuses = payload.get("statuses") or []
    status_map: dict[str, object] = {}
    if isinstance(statuses, list):
        for item in statuses:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if code:
                status_map[code] = item.get("value")
    controls = payload.get("controls") or []
    control_codes = {str(item).strip() for item in controls if str(item).strip()}
    return status_map, control_codes, payload


def _build_switch_channels(device: Device) -> list[dict]:
    status_map, raw_control_codes, payload = _parse_status_payload(device.last_status_payload)
    control_codes = set(device.control_codes) | raw_control_codes
    candidate_codes = {code for code in control_codes | set(status_map) if _is_switch_like_code(code)}
    aliases = device.channel_aliases
    channels: list[dict] = []
    usb_count = len([code for code in candidate_codes if code.startswith("switch_usb")])
    for code in sorted(candidate_codes, key=_switch_code_sort_key):
        value = status_map.get(code)
        if code == "switch":
            label = "Главное питание"
            group = "main"
        elif code == "switch_usb":
            label = "USB блок"
            group = "usb"
        elif re.fullmatch(r"switch_(\d+)", code):
            idx = re.fullmatch(r"switch_(\d+)", code).group(1)
            label = f"Розетка {idx}"
            group = "socket"
        else:
            match = re.fullmatch(r"switch_usb(\d+)", code)
            idx = match.group(1) if match else "?"
            label = "USB блок" if usb_count == 1 else f"USB {idx}"
            group = "usb"
        alias = aliases.get(code)
        channels.append({
            "code": code,
            "label": label,
            "display_label": alias or label,
            "alias": alias,
            "group": group,
            "is_on": value if isinstance(value, bool) else None,
            "status_text": "включён" if value is True else ("выключен" if value is False else "нет свежего статуса"),
            "supports_control": code in control_codes,
        })
    energy_caps = _build_energy_capabilities(payload, channels, status_map)
    for item in channels:
        item["metrics"] = energy_caps["channel_metrics"].get(item["code"], {})
    return channels


def _is_switch_like_code(code: str | None) -> bool:
    if not code:
        return False
    return bool(code == "switch" or re.fullmatch(r"switch_[1-9]\d*", code) or re.fullmatch(r"switch_usb[1-9]\d*", code) or code == "switch_usb")


def _channel_metric_definition(code: str) -> tuple[str, int] | None:
    mapping = {
        "add_ele": ("energy_kwh", 3),
        "cur_power": ("power_w", 1),
        "cur_voltage": ("voltage_v", 1),
        "cur_current": ("current_ma", 0),
    }
    return mapping.get(code)


def _scaled_metric_value(raw_value: object, scale: int) -> Decimal | None:
    if raw_value in (None, ""):
        return None
    try:
        value = Decimal(str(raw_value))
    except Exception:
        return None
    if scale > 0:
        value = value / (Decimal(10) ** scale)
    return value


def _channel_metric_match(code: str) -> tuple[str, str] | None:
    for prefix in ("add_ele", "cur_power", "cur_voltage", "cur_current"):
        patterns = (
            (rf"{prefix}_(\d+)", "switch_{idx}"),
            (rf"{prefix}_usb", "switch_usb"),
            (rf"{prefix}_usb(\d+)", "switch_usb{idx}"),
        )
        for pattern, template in patterns:
            match = re.fullmatch(pattern, code or "")
            if match:
                idx = match.group(1) if match.groups() else ""
                return template.format(idx=idx), prefix
    return None


def _format_metric_display(metric_key: str, value: Decimal | None) -> str | None:
    if value is None:
        return None
    if metric_key == "energy_kwh":
        return f"{value.quantize(Decimal('0.000'))} kWh"
    if metric_key == "power_w":
        return f"{_quantize(value)} W"
    if metric_key == "voltage_v":
        return f"{_quantize(value)} V"
    if metric_key == "current_ma":
        return f"{value.quantize(Decimal('0'))} mA"
    return str(value)


def _build_channel_metrics(status_map: dict[str, object], channels: list[dict]) -> tuple[dict[str, dict], list[str]]:
    metrics_by_channel = {item["code"]: {} for item in channels}
    found_codes: list[str] = []
    for code, raw_value in status_map.items():
        matched = _channel_metric_match(code)
        if not matched:
            continue
        channel_code, prefix = matched
        definition = _channel_metric_definition(prefix)
        if definition is None or channel_code not in metrics_by_channel:
            continue
        metric_key, scale = definition
        value = _scaled_metric_value(raw_value, scale)
        metrics_by_channel[channel_code][metric_key] = value
        metrics_by_channel[channel_code][f"{metric_key}_display"] = _format_metric_display(metric_key, value)
        found_codes.append(code)
    return metrics_by_channel, sorted(found_codes)


def _build_energy_capabilities(payload: dict[str, object], channels: list[dict], status_map: dict[str, object]) -> dict:
    status_codes = {str(item).strip() for item in (payload.get("status_codes") or []) if str(item).strip()}
    aggregate_codes = [code for code in ("add_ele", "cur_power", "cur_voltage", "cur_current") if code in status_codes or code in status_map]
    channel_metrics, channel_metric_codes = _build_channel_metrics(status_map, channels)
    supports_channel_metrics = bool(channel_metric_codes)
    if supports_channel_metrics:
        message = "Tuya отдаёт отдельные метрики по каналам — можно показывать реальные значения по каждой линии."
    elif aggregate_codes:
        message = "По этому устройству Tuya отдаёт только общие метрики устройства. Отдельных power/energy кодов по каналам не видно."
    else:
        message = "Tuya пока не отдала ни общих, ни поканальных кодов энергомониторинга для этого устройства."
    return {
        "aggregate_codes": aggregate_codes,
        "channel_metric_codes": channel_metric_codes,
        "supports_channel_metrics": supports_channel_metrics,
        "message": message,
        "channel_metrics": channel_metrics,
    }


def _build_channel_summary(channels: list[dict]) -> dict:
    sockets = [item for item in channels if item["group"] == "socket"]
    usb = [item for item in channels if item["group"] == "usb"]
    mains = [item for item in channels if item["group"] == "main"]
    return {
        "all": channels,
        "sockets": sockets,
        "usb": usb,
        "mains": mains,
        "has_channels": bool(channels),
        "has_power_strip_layout": bool(sockets or usb),
        "socket_count": len(sockets),
        "usb_count": len(usb),
        "aliased_total": len([item for item in channels if item.get("alias")]),
    }

def get_device_dashboard(db: Session, device: Device) -> dict:
    today = local_today()
    runtime = get_runtime_config(db)
    month_start = today.replace(day=1)

    daily_rows = db.execute(
        select(EnergySample)
        .where(EnergySample.device_id == device.id, EnergySample.bucket_type == BucketType.DAY)
        .order_by(EnergySample.period_start.desc())
        .limit(30)
    ).scalars().all()

    monthly_rows = db.execute(
        select(EnergySample)
        .where(EnergySample.device_id == device.id, EnergySample.bucket_type == BucketType.MONTH)
        .order_by(EnergySample.period_start.desc())
        .limit(12)
    ).scalars().all()

    snapshot_rows = db.execute(
        select(DeviceStatusSnapshot)
        .where(DeviceStatusSnapshot.device_id == device.id)
        .order_by(DeviceStatusSnapshot.recorded_at.desc(), DeviceStatusSnapshot.id.desc())
        .limit(120)
    ).scalars().all()

    recent_snapshots = snapshot_rows[:20]
    power_points = list(reversed(snapshot_rows))
    daily_chart_rows = list(reversed(daily_rows[:14]))
    monthly_chart_rows = list(reversed(monthly_rows[:12]))

    today_energy = next((row.energy_kwh for row in daily_rows if row.period_start == today), ZERO)
    month_energy = next((row.energy_kwh for row in monthly_rows if row.period_start == month_start), ZERO)

    power_values = [row.power_w for row in snapshot_rows if row.power_w is not None]
    voltage_values = [row.voltage_v for row in snapshot_rows if row.voltage_v is not None]
    temp_values = [row.current_temperature_c for row in snapshot_rows if row.current_temperature_c is not None]

    power_chart = build_line_chart(
        [
            {
                "label": format_local_datetime(row.recorded_at, "%H:%M:%S"),
                "value": row.power_w,
                "value_display": f"{_quantize(row.power_w)} W",
                "title": f"{format_local_datetime(row.recorded_at)} — {_quantize(row.power_w)} W",
            }
            for row in power_points
        ],
        suffix=" W",
    )

    daily_chart = build_bar_chart(
        [
            {
                "label": format_local_date(row.period_start, "%d-%m"),
                "value": row.energy_kwh,
                "value_display": f"{row.energy_kwh:.3f} kWh",
                "title": f"{format_local_date(row.period_start)} — {row.energy_kwh:.3f} kWh",
            }
            for row in daily_chart_rows
        ],
        suffix=" kWh",
    )

    monthly_chart = build_bar_chart(
        [
            {
                "label": format_local_date(row.period_start, "%m-%Y"),
                "value": row.energy_kwh,
                "value_display": f"{row.energy_kwh:.3f} kWh",
                "title": f"{format_local_date(row.period_start)} — {row.energy_kwh:.3f} kWh",
            }
            for row in monthly_chart_rows
        ],
        suffix=" kWh",
    )

    cost_data = calculate_tariff_costs(db, runtime, device_ids=[device.id])["per_device"].get(device.id, {})

    control_codes = set(device.control_codes)
    target_min = _quantize(device.target_temperature_min_c) if device.target_temperature_min_c is not None else None
    target_max = _quantize(device.target_temperature_max_c) if device.target_temperature_max_c is not None else None
    target_step = _quantize(device.target_temperature_step_c) if device.target_temperature_step_c is not None else None
    channels = _build_switch_channels(device)
    channel_summary = _build_channel_summary(channels)
    status_map, _, payload = _parse_status_payload(device.last_status_payload)
    energy_capabilities = _build_energy_capabilities(payload, channels, status_map)

    return {
        "daily": daily_rows,
        "monthly": monthly_rows,
        "snapshots": recent_snapshots,
        "power_chart": power_chart,
        "daily_chart": daily_chart,
        "monthly_chart": monthly_chart,
        "stats": {
            "today_kwh": _quantize(today_energy, "0.000"),
            "month_kwh": _quantize(month_energy, "0.000"),
            "today_cost": _money(cost_data.get("today_cost", Decimal("0.00"))),
            "month_cost": _money(cost_data.get("month_cost", Decimal("0.00"))),
            "today_zone_costs": cost_data.get("today_zones_list", []),
            "month_zone_costs": cost_data.get("month_zones_list", []),
            "today_breakdown": _zone_breakdown(cost_data.get("today_zones_list", []), runtime.tariff_currency),
            "month_breakdown": _zone_breakdown(cost_data.get("month_zones_list", []), runtime.tariff_currency),
            "tariff_display": runtime.tariff_display,
            "tariff_currency": runtime.tariff_currency,
            "tariff_mode_label": runtime.tariff_mode_label,
            "latest_power_w": _quantize(device.current_power_w),
            "latest_voltage_v": _quantize(device.current_voltage_v),
            "peak_power_w": _quantize(max(power_values) if power_values else Decimal("0.00")),
            "max_voltage_v": _quantize(max(voltage_values) if voltage_values else Decimal("0.00")),
            "latest_temperature_c": _quantize(device.current_temperature_c) if device.current_temperature_c is not None else None,
            "target_temperature_c": _quantize(device.target_temperature_c) if device.target_temperature_c is not None else None,
            "peak_temperature_c": _quantize(max(temp_values) if temp_values else device.current_temperature_c) if (temp_values or device.current_temperature_c is not None) else None,
            "snapshots_total": len(snapshot_rows),
        },
        "profile": {
            "key": device.device_profile,
            "label": _profile_label(device.device_profile),
            "is_boiler": device.device_profile == 'boiler',
            "is_temperature": device.current_temperature_c is not None or device.target_temperature_c is not None,
            "badge_name": device.badge.name if device.badge is not None else None,
            "badge_color": device.badge.color if device.badge is not None else None,
        },
        "boiler": {
            "has_temperature": device.current_temperature_c is not None or device.target_temperature_c is not None,
            "current_temperature_c": _quantize(device.current_temperature_c) if device.current_temperature_c is not None else None,
            "target_temperature_c": _quantize(device.target_temperature_c) if device.target_temperature_c is not None else None,
            "operation_mode": device.operation_mode,
            "operation_mode_label": _label_mode(device.operation_mode),
            "fault_code": device.fault_code,
            "temp_range_label": f"{target_min}…{target_max} °C · шаг {target_step} °C" if target_min is not None and target_max is not None and target_step is not None else None,
        },
        "channels": channel_summary,
        "energy_capabilities": energy_capabilities,
        "controls": {
            "codes": sorted(control_codes),
            "supports_switch": ('switch' in control_codes) or (len([code for code in control_codes if _is_switch_like_code(code)]) == 1),
            "supports_mode": 'mode' in control_codes,
            "supports_target_temperature": 'temp_set' in control_codes,
            "available_modes": list(device.available_modes),
            "target_temperature_min_c": target_min,
            "target_temperature_max_c": target_max,
            "target_temperature_step_c": target_step,
            "switch_channels": channels,
            "supports_multi_switch": len([code for code in control_codes if _is_switch_like_code(code)]) > 1,
        },
    }
