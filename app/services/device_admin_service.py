from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import Device, ProviderType


def restore_non_demo_deleted_devices(db: Session) -> int:
    restored = db.execute(
        update(Device)
        .where(Device.provider != ProviderType.DEMO, Device.is_deleted.is_(True))
        .values(
            is_deleted=False,
            deleted_reason=None,
            deleted_at=None,
            is_hidden=False,
            hidden_reason=None,
        )
    ).rowcount or 0
    db.commit()
    return int(restored)



def purge_demo_devices(db: Session) -> int:
    demo_ids = db.execute(select(Device.id).where(Device.provider == ProviderType.DEMO)).scalars().all()
    if not demo_ids:
        return 0
    db.execute(delete(Device).where(Device.id.in_(demo_ids)))
    db.commit()
    return len(demo_ids)
