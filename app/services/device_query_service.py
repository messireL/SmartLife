from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Device, DeviceBadge


TEMP_NAME_PREFIXES = ("temp", "tmp", "temporary")


def is_temp_device_name(name: str | None) -> bool:
    if not name:
        return False
    lowered = name.strip().lower()
    return lowered.startswith(TEMP_NAME_PREFIXES)


def _display_name_expr():
    return func.coalesce(func.nullif(Device.custom_name, ""), Device.name)


def _display_room_expr():
    return func.coalesce(func.nullif(Device.custom_room_name, ""), Device.room_name)


def get_devices_for_ui(
    db: Session,
    *,
    include_hidden: bool = False,
    query: str = "",
    only_online: bool = False,
    only_powered: bool = False,
    hide_temp: bool = True,
    provider_filter: str = "",
    room_filter: str = "",
    badge_filter: str = "",
):
    stmt = select(Device).options(selectinload(Device.badge))
    stmt = stmt.where(Device.is_deleted.is_(False))
    if not include_hidden:
        stmt = stmt.where(Device.is_hidden.is_(False))
    if only_online:
        stmt = stmt.where(Device.is_online.is_(True))
    if only_powered:
        stmt = stmt.where(Device.switch_on.is_(True))
    if provider_filter.strip():
        stmt = stmt.where(Device.provider == provider_filter.strip())
    if room_filter.strip():
        stmt = stmt.where(_display_room_expr() == room_filter.strip())
    if badge_filter.strip():
        value = badge_filter.strip()
        if value == "__none__":
            stmt = stmt.where(Device.badge_id.is_(None))
        else:
            stmt = stmt.join(DeviceBadge, Device.badge_id == DeviceBadge.id).where(DeviceBadge.key == value)
    if query.strip():
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                Device.name.ilike(like),
                Device.custom_name.ilike(like),
                Device.room_name.ilike(like),
                Device.custom_room_name.ilike(like),
                Device.model.ilike(like),
                Device.product_name.ilike(like),
                Device.category.ilike(like),
            )
        )
    devices = db.execute(
        stmt.order_by(_display_room_expr().asc().nullslast(), _display_name_expr().asc(), Device.id.asc())
    ).scalars().all()
    if hide_temp:
        devices = [device for device in devices if not is_temp_device_name(device.display_name)]
    return devices


def get_room_choices(db: Session) -> list[str]:
    room_expr = func.nullif(_display_room_expr(), "").label("room_name")
    room_subquery = (
        select(room_expr)
        .where(Device.is_deleted.is_(False))
        .where(room_expr.is_not(None))
        .distinct()
        .subquery()
    )
    rows = db.execute(select(room_subquery.c.room_name).order_by(room_subquery.c.room_name.asc())).all()
    return [row[0] for row in rows if row[0]]


def get_provider_choices(db: Session) -> list[str]:
    rows = db.execute(
        select(Device.provider).where(Device.is_deleted.is_(False)).distinct().order_by(Device.provider.asc())
    ).all()
    return [row[0].value if hasattr(row[0], "value") else str(row[0]) for row in rows if row[0]]


def get_badge_choices(db: Session) -> list[DeviceBadge]:
    return db.execute(select(DeviceBadge).order_by(DeviceBadge.name.asc(), DeviceBadge.id.asc())).scalars().all()
