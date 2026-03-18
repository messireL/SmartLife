from __future__ import annotations

import json
import threading
import time
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.timeutils import utc_now_naive
from app.db.init_db import init_db
from app.db.models import SyncRun, SyncRunStatus, SyncRunTrigger
from app.db.session import SessionLocal
from app.services.sync_service import sync_from_provider

_sync_lock = threading.Lock()


class SyncAlreadyRunningError(RuntimeError):
    pass



def is_sync_running() -> bool:
    return _sync_lock.locked()



def run_sync_job(*, trigger: SyncRunTrigger = SyncRunTrigger.MANUAL, fail_if_running: bool = False) -> dict[str, Any]:
    init_db()

    acquired = _sync_lock.acquire(blocking=not fail_if_running)
    if not acquired:
        if fail_if_running:
            raise SyncAlreadyRunningError("sync job already running")
        return {
            "status": "skipped",
            "reason": "sync job already running",
            "trigger": trigger.value,
            "provider": get_settings().smartlife_provider,
        }

    started_at = utc_now_naive()
    start_perf = time.perf_counter()

    try:
        with SessionLocal() as db:
            provider = get_settings().smartlife_provider
            sync_run = SyncRun(
                provider=provider,
                trigger=trigger,
                status=SyncRunStatus.RUNNING,
                started_at=started_at,
            )
            db.add(sync_run)
            db.commit()
            db.refresh(sync_run)

            try:
                result = sync_from_provider(db, trigger=trigger)
                finished_at = utc_now_naive()
                duration_ms = int((time.perf_counter() - start_perf) * 1000)
                sync_run.status = SyncRunStatus.SUCCESS
                sync_run.finished_at = finished_at
                sync_run.duration_ms = duration_ms
                sync_run.result_summary = json.dumps(result, ensure_ascii=False, default=str, sort_keys=True)
                sync_run.error_message = None
                db.commit()
                return {
                    "status": sync_run.status.value,
                    "trigger": trigger.value,
                    "provider": provider,
                    "duration_ms": duration_ms,
                    "result": result,
                    "sync_run_id": sync_run.id,
                }
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                finished_at = utc_now_naive()
                duration_ms = int((time.perf_counter() - start_perf) * 1000)
                sync_run = db.get(SyncRun, sync_run.id)
                if sync_run is not None:
                    sync_run.status = SyncRunStatus.ERROR
                    sync_run.finished_at = finished_at
                    sync_run.duration_ms = duration_ms
                    sync_run.error_message = str(exc)
                    db.commit()
                raise
    finally:
        _sync_lock.release()



def get_recent_sync_runs(limit: int = 10) -> list[SyncRun]:
    init_db()
    with SessionLocal() as db:
        return db.execute(select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(limit)).scalars().all()



def get_last_sync_run() -> SyncRun | None:
    items = get_recent_sync_runs(limit=1)
    return items[0] if items else None
