from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DeviceCommandLog, DeviceCommandStatus, ProviderType, SyncRun, SyncRunStatus
from app.services.runtime_config_service import RuntimeConfig

_TUYA_QUOTA_ERROR_CODE = "28841004"
_TUYA_QUOTA_HINTS = (
    "trial edition is used up",
    "please upgrade to the official version",
    "quota of trial edition is used up",
)


@dataclass(slots=True)
class TuyaQuotaState:
    exhausted: bool
    code: str | None = None
    message: str | None = None
    detected_at: datetime | None = None
    source: str | None = None
    last_success_at: datetime | None = None

    @property
    def banner_title(self) -> str:
        return "Квота Tuya Trial исчерпана" if self.exhausted else "Квота Tuya Trial в норме"

    @property
    def banner_message(self) -> str:
        if self.exhausted:
            return (
                "Tuya перестала принимать cloud-команды и может резать sync, потому что у Trial Edition "
                "закончился месячный лимит API. Продли Extended Trial или включи платный ресурс-пак, "
                "а потом нажми «Синхронизировать сейчас», чтобы SmartLife увидел, что облако снова живо."
            )
        return ""


@dataclass(slots=True)
class _QuotaSignal:
    detected_at: datetime
    source: str
    message: str


def is_tuya_quota_error_message(message: str | None) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    if _TUYA_QUOTA_ERROR_CODE in text:
        return True
    return any(hint in text for hint in _TUYA_QUOTA_HINTS)



def _latest_quota_command_error(db: Session) -> _QuotaSignal | None:
    rows = db.execute(
        select(DeviceCommandLog)
        .where(
            DeviceCommandLog.provider == ProviderType.TUYA_CLOUD.value,
            DeviceCommandLog.status == DeviceCommandStatus.ERROR,
            DeviceCommandLog.error_message.is_not(None),
        )
        .order_by(DeviceCommandLog.requested_at.desc(), DeviceCommandLog.id.desc())
        .limit(25)
    ).scalars().all()
    for row in rows:
        if is_tuya_quota_error_message(row.error_message):
            return _QuotaSignal(
                detected_at=row.requested_at,
                source="device_command",
                message=str(row.error_message or "").strip(),
            )
    return None



def _latest_quota_sync_error(db: Session) -> _QuotaSignal | None:
    rows = db.execute(
        select(SyncRun)
        .where(
            SyncRun.provider == ProviderType.TUYA_CLOUD.value,
            SyncRun.status == SyncRunStatus.ERROR,
            SyncRun.error_message.is_not(None),
        )
        .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        .limit(25)
    ).scalars().all()
    for row in rows:
        if is_tuya_quota_error_message(row.error_message):
            return _QuotaSignal(
                detected_at=row.started_at,
                source="sync",
                message=str(row.error_message or "").strip(),
            )
    return None



def _latest_success_at(db: Session) -> datetime | None:
    latest_command_success = db.execute(
        select(DeviceCommandLog)
        .where(
            DeviceCommandLog.provider == ProviderType.TUYA_CLOUD.value,
            DeviceCommandLog.status == DeviceCommandStatus.SUCCESS,
        )
        .order_by(DeviceCommandLog.requested_at.desc(), DeviceCommandLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_sync_success = db.execute(
        select(SyncRun)
        .where(
            SyncRun.provider == ProviderType.TUYA_CLOUD.value,
            SyncRun.status == SyncRunStatus.SUCCESS,
        )
        .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    timestamps = [
        latest_command_success.requested_at if latest_command_success and latest_command_success.requested_at else None,
        latest_sync_success.started_at if latest_sync_success and latest_sync_success.started_at else None,
    ]
    timestamps = [item for item in timestamps if item is not None]
    return max(timestamps) if timestamps else None



def detect_tuya_quota_state(db: Session, *, runtime: RuntimeConfig | None = None) -> TuyaQuotaState:
    runtime = runtime
    if runtime is not None and runtime.provider != ProviderType.TUYA_CLOUD.value:
        return TuyaQuotaState(exhausted=False)

    command_error = _latest_quota_command_error(db)
    sync_error = _latest_quota_sync_error(db)
    latest_error = None
    if command_error and sync_error:
        latest_error = command_error if command_error.detected_at >= sync_error.detected_at else sync_error
    else:
        latest_error = command_error or sync_error

    latest_success_at = _latest_success_at(db)
    if latest_error is None:
        return TuyaQuotaState(exhausted=False, last_success_at=latest_success_at)

    exhausted = latest_success_at is None or latest_error.detected_at >= latest_success_at
    return TuyaQuotaState(
        exhausted=exhausted,
        code=_TUYA_QUOTA_ERROR_CODE,
        message=latest_error.message,
        detected_at=latest_error.detected_at,
        source=latest_error.source,
        last_success_at=latest_success_at,
    )
