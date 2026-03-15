from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import utc_now_naive
from app.db.models import Device, DeviceCommandLog, DeviceCommandStatus, SyncRunTrigger
from app.integrations.registry import get_provider


class DeviceControlError(RuntimeError):
    pass



def get_recent_command_logs(db: Session, device_id: int, limit: int = 10) -> list[DeviceCommandLog]:
    limit = max(1, min(limit, 50))
    return db.execute(
        select(DeviceCommandLog)
        .where(DeviceCommandLog.device_id == device_id)
        .order_by(DeviceCommandLog.requested_at.desc(), DeviceCommandLog.id.desc())
        .limit(limit)
    ).scalars().all()



def set_device_switch_state(db: Session, device_id: int, desired_state: bool, *, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = db.get(Device, device_id)
    if device is None:
        raise DeviceControlError('device not found')

    provider = get_provider()
    if getattr(provider, 'provider_name', None) != device.provider:
        raise DeviceControlError('active provider does not match selected device provider')

    requested_at = utc_now_naive()

    try:
        if not hasattr(provider, 'send_switch_command'):
            raise DeviceControlError(f'provider {device.provider.value} does not support switch commands yet')
        result = provider.send_switch_command(device.external_id, desired_state)
        device.switch_on = desired_state
        device.last_status_at = utc_now_naive()
        db.add(
            DeviceCommandLog(
                device_id=device.id,
                command_code='switch_1',
                command_value='true' if desired_state else 'false',
                status=DeviceCommandStatus.SUCCESS,
                provider=device.provider.value,
                requested_at=requested_at,
                finished_at=utc_now_naive(),
                result_summary=json.dumps(result, ensure_ascii=False, default=str, sort_keys=True),
            )
        )
        db.commit()
        return {
            'status': 'success',
            'device_id': device.id,
            'switch_on': desired_state,
            'provider': device.provider.value,
            'result': result,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        db.add(
            DeviceCommandLog(
                device_id=device.id,
                command_code='switch_1',
                command_value='true' if desired_state else 'false',
                status=DeviceCommandStatus.ERROR,
                provider=device.provider.value,
                requested_at=requested_at,
                finished_at=utc_now_naive(),
                error_message=str(exc),
                result_summary=f'trigger={trigger}',
            )
        )
        db.commit()
        raise DeviceControlError(str(exc)) from exc
