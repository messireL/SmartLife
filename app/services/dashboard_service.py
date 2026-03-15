from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import format_local_date, format_local_datetime, local_today
from app.db.models import BucketType, Device, DeviceStatusSnapshot, EnergySample, SyncRun, SyncRunStatus
from app.services.chart_service import build_bar_chart, build_line_chart
from app.services.sync_runner import is_sync_running
from app.services.runtime_config_service import get_runtime_config


ZERO = Decimal("0.000")



def _quantize(value: Decimal | None, places: str = "0.00") -> Decimal:
    if value is None:
        return Decimal(places)
    return value.quantize(Decimal(places))



def _money(value: Decimal | None) -> Decimal:
    return _quantize(value, "0.00")


def get_dashboard_summary(db: Session) -> dict:
    today = local_today()
    month_start = today.replace(day=1)
    runtime = get_runtime_config(db)
    tariff_price = runtime.tariff_price_decimal


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

    day_cost = (day_total or ZERO) * tariff_price
    month_cost = (month_total or ZERO) * tariff_price

    return {
        "devices_total": devices_total,
        "online_total": online_total,
        "powered_on_total": powered_on_total,
        "day_total_kwh": _quantize(day_total, "0.000"),
        "month_total_kwh": _quantize(month_total, "0.000"),
        "day_total_cost": _money(day_cost),
        "month_total_cost": _money(month_cost),
        "tariff_price_per_kwh": runtime.tariff_price_decimal,
        "tariff_currency": runtime.tariff_currency,
        "tariff_display": runtime.tariff_display,
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
    tariff_price = runtime.tariff_price_decimal
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
        {"device": device, "energy_kwh": energy, "cost": _money(energy * tariff_price)}
        for device, energy in top_today_rows
    ]
    top_cost_month_rows = [
        {"device": device, "energy_kwh": energy, "cost": _money(energy * tariff_price)}
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
        "tariff_currency": runtime.tariff_currency,
        "trend_period_label": f"{format_local_date(trend_start)} — {format_local_date(today)}",
    }



def get_device_dashboard(db: Session, device: Device) -> dict:
    today = local_today()
    runtime = get_runtime_config(db)
    tariff_price = runtime.tariff_price_decimal
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
            "today_cost": _money(today_energy * tariff_price),
            "month_cost": _money(month_energy * tariff_price),
            "tariff_display": runtime.tariff_display,
            "tariff_currency": runtime.tariff_currency,
            "latest_power_w": _quantize(device.current_power_w),
            "latest_voltage_v": _quantize(device.current_voltage_v),
            "peak_power_w": _quantize(max(power_values) if power_values else Decimal("0.00")),
            "max_voltage_v": _quantize(max(voltage_values) if voltage_values else Decimal("0.00")),
            "snapshots_total": len(snapshot_rows),
        },
    }
