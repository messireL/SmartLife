from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutils import local_today
from app.db.models import BucketType, Device, EnergySample
from app.services.device_query_service import get_room_choices


ZERO = Decimal('0.000')


def get_rooms_overview(db: Session) -> list[dict]:
    today = local_today()
    month_start = today.replace(day=1)
    rooms = []
    room_expr = func.coalesce(func.nullif(Device.custom_room_name, ''), Device.room_name)
    name_expr = func.coalesce(func.nullif(Device.custom_name, ''), Device.name)
    for room_name in get_room_choices(db):
        room_devices = db.execute(
            select(Device)
            .where(Device.is_deleted.is_(False))
            .where(room_expr == room_name)
            .order_by(name_expr.asc())
        ).scalars().all()
        visible_devices = [d for d in room_devices if not d.is_hidden]
        if not room_devices or not visible_devices:
            continue
        device_ids = [d.id for d in room_devices]
        today_energy = db.scalar(
            select(func.coalesce(func.sum(EnergySample.energy_kwh), ZERO)).where(
                EnergySample.device_id.in_(device_ids),
                EnergySample.bucket_type == BucketType.DAY,
                EnergySample.period_start == today,
            )
        ) or ZERO
        month_energy = db.scalar(
            select(func.coalesce(func.sum(EnergySample.energy_kwh), ZERO)).where(
                EnergySample.device_id.in_(device_ids),
                EnergySample.bucket_type == BucketType.MONTH,
                EnergySample.period_start == month_start,
            )
        ) or ZERO
        live_power = sum(((d.current_power_w or Decimal('0.00')) for d in visible_devices), Decimal('0.00'))
        rooms.append(
            {
                'name': room_name,
                'devices_total': len(visible_devices),
                'online_total': sum(1 for d in visible_devices if d.is_online),
                'powered_total': sum(1 for d in visible_devices if d.switch_on is True),
                'today_kwh': today_energy.quantize(Decimal('0.001')),
                'month_kwh': month_energy.quantize(Decimal('0.001')),
                'live_power_w': live_power.quantize(Decimal('0.01')),
                'top_devices': sorted(visible_devices, key=lambda d: (d.current_power_w or Decimal('0.00')), reverse=True)[:4],
            }
        )
    rooms.sort(key=lambda item: item['name'].lower())
    return rooms
