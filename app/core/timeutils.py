from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def get_app_timezone() -> ZoneInfo:
    tz_name = get_settings().timezone or "Europe/Helsinki"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Europe/Helsinki")


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return _as_utc(dt).astimezone(get_app_timezone())


def local_today() -> date:
    return datetime.now(get_app_timezone()).date()


def local_day_start_from_utc(dt: datetime) -> date:
    local_dt = to_local(dt)
    return local_dt.date()


def local_month_start_from_utc(dt: datetime) -> date:
    local_dt = to_local(dt)
    return local_dt.date().replace(day=1)


def format_local_datetime(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    local_dt = to_local(dt)
    if local_dt is None:
        return "—"
    suffix = local_dt.tzname() or ""
    return f"{local_dt.strftime(fmt)} {suffix}".strip()
