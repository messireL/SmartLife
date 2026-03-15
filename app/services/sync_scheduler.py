from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from app.core.config import get_settings
from app.db.models import SyncRunTrigger
from app.services.sync_runner import run_sync_job

logger = logging.getLogger(__name__)


async def run_background_sync_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(15, settings.smartlife_sync_interval_seconds)
    first_cycle = True

    while not stop_event.is_set():
        should_run = settings.smartlife_sync_on_startup if first_cycle else settings.smartlife_background_sync_enabled
        trigger = SyncRunTrigger.STARTUP if first_cycle else SyncRunTrigger.BACKGROUND

        if should_run:
            try:
                await asyncio.to_thread(run_sync_job, trigger=trigger, fail_if_running=False)
            except Exception:  # noqa: BLE001
                logger.exception("Background sync failed")

        first_cycle = False

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue


async def stop_background_task(task: asyncio.Task | None, stop_event: asyncio.Event | None) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
