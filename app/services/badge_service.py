from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Device, DeviceBadge

ALLOWED_BADGE_COLORS = {"blue", "green", "purple", "amber", "rose", "slate"}


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", (value or "").strip().lower(), flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "badge"


def _normalize_color(value: str | None) -> str:
    color = (value or "slate").strip().lower()
    return color if color in ALLOWED_BADGE_COLORS else "slate"


def list_badges(db: Session) -> list[dict]:
    rows = db.execute(
        select(DeviceBadge, func.count(Device.id))
        .outerjoin(Device, Device.badge_id == DeviceBadge.id)
        .group_by(DeviceBadge.id)
        .order_by(DeviceBadge.name.asc(), DeviceBadge.id.asc())
    ).all()
    return [
        {
            "id": badge.id,
            "key": badge.key,
            "name": badge.name,
            "color": badge.color,
            "assigned_total": int(assigned_total or 0),
        }
        for badge, assigned_total in rows
    ]


def get_badge_choices(db: Session) -> list[DeviceBadge]:
    return db.execute(select(DeviceBadge).order_by(DeviceBadge.name.asc(), DeviceBadge.id.asc())).scalars().all()


def create_badge(db: Session, *, name: str, color: str) -> DeviceBadge:
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("Название плашки не должно быть пустым.")
    normalized_color = _normalize_color(color)
    base_key = _slugify(cleaned_name)
    key = base_key
    suffix = 2
    while db.execute(select(DeviceBadge.id).where(DeviceBadge.key == key)).scalar_one_or_none() is not None:
        key = f"{base_key}-{suffix}"
        suffix += 1
    badge = DeviceBadge(key=key, name=cleaned_name[:64], color=normalized_color)
    db.add(badge)
    db.commit()
    db.refresh(badge)
    return badge


def delete_badge(db: Session, badge_id: int) -> tuple[DeviceBadge | None, int]:
    badge = db.get(DeviceBadge, badge_id)
    if badge is None:
        return None, 0
    devices = db.execute(select(Device).where(Device.badge_id == badge_id, Device.is_deleted.is_(False))).scalars().all()
    for device in devices:
        device.badge_id = None
    db.delete(badge)
    db.commit()
    return badge, len(devices)


def assign_badge_to_devices(db: Session, devices: Iterable[Device], badge_id: int | None) -> int:
    updated = 0
    for device in devices:
        device.badge_id = badge_id
        updated += 1
    db.commit()
    return updated
