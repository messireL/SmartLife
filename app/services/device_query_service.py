from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Device


TEMP_NAME_PREFIXES = ("temp", "tmp", "temporary")


def is_temp_device_name(name: str | None) -> bool:
    if not name:
        return False
    lowered = name.strip().lower()
    return lowered.startswith(TEMP_NAME_PREFIXES)


def get_devices_for_ui(
    db: Session,
    *,
    include_hidden: bool = False,
    query: str = "",
    only_online: bool = False,
    only_powered: bool = False,
    hide_temp: bool = True,
):
    stmt = select(Device)
    if not include_hidden:
        stmt = stmt.where(Device.is_hidden.is_(False))
    if only_online:
        stmt = stmt.where(Device.is_online.is_(True))
    if only_powered:
        stmt = stmt.where(Device.switch_on.is_(True))
    if query.strip():
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                Device.name.ilike(like),
                Device.room_name.ilike(like),
                Device.model.ilike(like),
                Device.product_name.ilike(like),
                Device.category.ilike(like),
            )
        )
    devices = db.execute(stmt.order_by(Device.room_name.asc(), Device.name.asc(), Device.id.asc())).scalars().all()
    if hide_temp:
        devices = [device for device in devices if not is_temp_device_name(device.name)]
    return devices
