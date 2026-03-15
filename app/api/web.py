from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import format_local_date, format_local_datetime
from app.db.models import Device, SyncRun, SyncRunTrigger
from app.db.session import get_db
from app.services.backup_service import list_backups
from app.services.dashboard_service import (
    get_dashboard_panels,
    get_dashboard_summary,
    get_device_dashboard,
    get_sync_overview,
)
from app.services.device_control_service import DeviceControlError, get_recent_command_logs, set_device_switch_state
from app.services.device_query_service import get_devices_for_ui, get_provider_choices, get_room_choices
from app.services.room_service import get_rooms_overview
from app.services.sync_runner import SyncAlreadyRunningError, run_sync_job
from app.services.runtime_config_service import (
    configure_demo_provider,
    configure_tariff_settings,
    configure_tuya_cloud,
    get_next_scheduled_tariff_plan,
    get_runtime_config,
    get_tariff_change_target_month,
    get_tariff_editor_plan,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
templates.env.globals["app_settings"] = settings
templates.env.filters["localdt"] = lambda value: format_local_datetime(value)
templates.env.filters["localdate"] = lambda value: format_local_date(value)
templates.env.filters["urlq"] = lambda value: quote_plus(str(value or ""))


NAV_ITEMS = [
    {"key": "overview", "href": "/", "label": "Главная"},
    {"key": "devices", "href": "/devices", "label": "Устройства"},
    {"key": "rooms", "href": "/rooms", "label": "Комнаты"},
    {"key": "consumption", "href": "/consumption", "label": "Потребление"},
    {"key": "sync", "href": "/sync", "label": "Синхронизация"},
    {"key": "settings", "href": "/settings", "label": "Настройки"},
    {"key": "backups", "href": "/backups", "label": "Резервные копии"},
]


def _base_context(*, request: Request, active_nav: str, page_title: str, flash: str | None = None, refresh_seconds: int | None = None, auto_refresh: bool = False, runtime: object | None = None) -> dict:
    return {
        "request": request,
        "settings": settings,
        "app_settings": settings,
        "nav_items": NAV_ITEMS,
        "active_nav": active_nav,
        "page_title": page_title,
        "flash": flash or request.query_params.get("flash"),
        "refresh_seconds": refresh_seconds,
        "auto_refresh": auto_refresh,
        "runtime": runtime,
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, auto_refresh: bool = Query(default=True), db: Session = Depends(get_db)):
    refresh_seconds = settings.smartlife_sync_interval_seconds if auto_refresh and settings.smartlife_background_sync_enabled else None
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="overview", page_title="Главная", refresh_seconds=refresh_seconds, auto_refresh=auto_refresh, runtime=runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "sync_overview": get_sync_overview(db),
            "dashboard_panels": get_dashboard_panels(db),
            "devices": get_devices_for_ui(db, query="", hide_temp=True)[:8],
            "rooms": get_rooms_overview(db)[:6],
        }
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/devices", response_class=HTMLResponse)
def devices_page(
    request: Request,
    q: str = Query(default=""),
    only_online: bool = Query(default=False),
    only_powered: bool = Query(default=False),
    include_hidden: bool = Query(default=False),
    show_temp: bool = Query(default=False),
    provider_filter: str = Query(default=""),
    room_filter: str = Query(default=""),
    auto_refresh: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    devices = get_devices_for_ui(
        db,
        include_hidden=include_hidden,
        query=q,
        only_online=only_online,
        only_powered=only_powered,
        hide_temp=not show_temp,
        provider_filter=provider_filter,
        room_filter=room_filter,
    )
    hidden_total = db.execute(select(Device).where(Device.is_hidden.is_(True), Device.is_deleted.is_(False))).scalars().all()
    refresh_seconds = settings.smartlife_sync_interval_seconds if auto_refresh and settings.smartlife_background_sync_enabled else None
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="devices", page_title="Устройства", refresh_seconds=refresh_seconds, auto_refresh=auto_refresh, runtime=runtime)
    context.update(
        {
            "devices": devices,
            "filters": {
                "q": q,
                "only_online": only_online,
                "only_powered": only_powered,
                "include_hidden": include_hidden,
                "show_temp": show_temp,
                "auto_refresh": auto_refresh,
                "provider_filter": provider_filter,
                "room_filter": room_filter,
            },
            "provider_choices": get_provider_choices(db),
            "room_choices": get_room_choices(db),
            "hidden_total": len(hidden_total),
            "summary": get_dashboard_summary(db),
        }
    )
    return templates.TemplateResponse(request, "devices.html", context)


@router.get("/rooms", response_class=HTMLResponse)
def rooms_page(request: Request, auto_refresh: bool = Query(default=True), db: Session = Depends(get_db)):
    refresh_seconds = settings.smartlife_sync_interval_seconds if auto_refresh and settings.smartlife_background_sync_enabled else None
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="rooms", page_title="Комнаты", refresh_seconds=refresh_seconds, auto_refresh=auto_refresh, runtime=runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "rooms": get_rooms_overview(db),
        }
    )
    return templates.TemplateResponse(request, "rooms.html", context)


@router.get("/consumption", response_class=HTMLResponse)
def consumption_page(request: Request, auto_refresh: bool = Query(default=True), db: Session = Depends(get_db)):
    refresh_seconds = settings.smartlife_sync_interval_seconds if auto_refresh and settings.smartlife_background_sync_enabled else None
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="consumption", page_title="Потребление", refresh_seconds=refresh_seconds, auto_refresh=auto_refresh, runtime=runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "dashboard_panels": get_dashboard_panels(db),
        }
    )
    return templates.TemplateResponse(request, "consumption.html", context)


@router.get("/sync", response_class=HTMLResponse)
def sync_page(request: Request, auto_refresh: bool = Query(default=True), db: Session = Depends(get_db)):
    recent_sync_runs = db.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(20)
    ).scalars().all()
    refresh_seconds = settings.smartlife_sync_interval_seconds if auto_refresh and settings.smartlife_background_sync_enabled else None
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="sync", page_title="Синхронизация", refresh_seconds=refresh_seconds, auto_refresh=auto_refresh, runtime=runtime)
    context.update(
        {
            "sync_overview": get_sync_overview(db),
            "recent_sync_runs": recent_sync_runs,
            "summary": get_dashboard_summary(db),
        }
    )
    return templates.TemplateResponse(request, "sync.html", context)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    runtime = get_runtime_config(db)
    tariff_editor_plan = get_tariff_editor_plan(db)
    next_tariff_plan = get_next_scheduled_tariff_plan(db)
    change_target_month = get_tariff_change_target_month()
    context = _base_context(request=request, active_nav="settings", page_title="Настройки", runtime=runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "sync_overview": get_sync_overview(db),
            "tariff_editor_plan": tariff_editor_plan,
            "next_tariff_plan": next_tariff_plan,
            "tariff_change_target_month": change_target_month,
        }
    )
    return templates.TemplateResponse(request, "settings.html", context)


@router.post("/settings/runtime-cloud")
def update_runtime_cloud_settings(
    provider: str = Form(default="tuya_cloud"),
    tuya_base_url: str = Form(default="https://openapi.tuyaeu.com"),
    tuya_access_id: str = Form(default=""),
    tuya_access_secret: str = Form(default=""),
    tuya_project_code: str = Form(default=""),
    db: Session = Depends(get_db),
):
    runtime = get_runtime_config(db)
    provider = (provider or "").strip()

    if provider == "demo":
        configure_demo_provider(db)
        flash = "Провайдер переключён на demo. Tuya-настройки сохранены в БД и могут быть включены позже."
        return RedirectResponse(url=f"/settings?flash={quote_plus(flash)}", status_code=303)

    base_url = (tuya_base_url or "").strip() or runtime.tuya_base_url or "https://openapi.tuyaeu.com"
    access_id = (tuya_access_id or "").strip() or runtime.tuya_access_id
    access_secret = (tuya_access_secret or "").strip() or runtime.tuya_access_secret
    project_code = (tuya_project_code or "").strip()

    if not access_id or not access_secret:
        flash = "Tuya Access ID и Access Secret обязательны. Secret можно оставить пустым только если он уже сохранён в БД."
        return RedirectResponse(url=f"/settings?flash={quote_plus(flash)}", status_code=303)

    configure_tuya_cloud(
        db,
        base_url=base_url,
        access_id=access_id,
        access_secret=access_secret,
        project_code=project_code,
    )
    flash = "Облачные настройки сохранены в PostgreSQL. Провайдер переключён на tuya_cloud."
    return RedirectResponse(url=f"/settings?flash={quote_plus(flash)}", status_code=303)




@router.post("/settings/tariff")
def update_tariff_settings(
    tariff_mode: str = Form(default="flat"),
    tariff_currency: str = Form(default="₽"),
    tariff_flat_price_per_kwh: str = Form(default="0.00"),
    tariff_two_day_price_per_kwh: str = Form(default="0.00"),
    tariff_two_night_price_per_kwh: str = Form(default="0.00"),
    tariff_two_day_start: str = Form(default="07:00"),
    tariff_two_night_start: str = Form(default="23:00"),
    tariff_three_day_price_per_kwh: str = Form(default="0.00"),
    tariff_three_night_price_per_kwh: str = Form(default="0.00"),
    tariff_three_peak_price_per_kwh: str = Form(default="0.00"),
    tariff_three_day_start: str = Form(default="07:00"),
    tariff_three_night_start: str = Form(default="23:00"),
    tariff_three_peak_morning_start: str = Form(default="07:00"),
    tariff_three_peak_morning_end: str = Form(default="10:00"),
    tariff_three_peak_evening_start: str = Form(default="17:00"),
    tariff_three_peak_evening_end: str = Form(default="21:00"),
    db: Session = Depends(get_db),
):
    from datetime import time
    from decimal import Decimal, InvalidOperation

    def _normalize_price(raw: str, label: str) -> str:
        raw = (raw or "0.00").strip().replace(",", ".")
        try:
            price = Decimal(raw)
            if price < 0:
                raise InvalidOperation
            return f"{price.quantize(Decimal('0.01'))}"
        except Exception:
            raise ValueError(f"Поле «{label}» должно быть неотрицательным числом, например 7.35")

    def _normalize_time(raw: str, label: str) -> str:
        raw = (raw or "").strip()
        try:
            hh, mm = raw.split(":", 1)
            parsed = time(int(hh), int(mm))
            return parsed.strftime("%H:%M")
        except Exception:
            raise ValueError(f"Поле «{label}» должно быть в формате ЧЧ:ММ, например 23:00")

    mode = (tariff_mode or "flat").strip()
    if mode not in {"flat", "two_zone", "three_zone"}:
        flash = "Неизвестный режим тарифа. Используй flat, two_zone или three_zone."
        return RedirectResponse(url=f"/settings?flash={quote_plus(flash)}", status_code=303)

    try:
        values = {
            "tariff.mode": mode,
            "tariff.currency": (tariff_currency or "₽").strip() or "₽",
            "tariff.flat.price_per_kwh": _normalize_price(tariff_flat_price_per_kwh, "Единый тариф"),
            "tariff.two_zone.day_price_per_kwh": _normalize_price(tariff_two_day_price_per_kwh, "Двухзонный день"),
            "tariff.two_zone.night_price_per_kwh": _normalize_price(tariff_two_night_price_per_kwh, "Двухзонная ночь"),
            "tariff.two_zone.day_start": _normalize_time(tariff_two_day_start, "Начало дня (2 зоны)"),
            "tariff.two_zone.night_start": _normalize_time(tariff_two_night_start, "Начало ночи (2 зоны)"),
            "tariff.three_zone.day_price_per_kwh": _normalize_price(tariff_three_day_price_per_kwh, "Трёхзонный день"),
            "tariff.three_zone.night_price_per_kwh": _normalize_price(tariff_three_night_price_per_kwh, "Трёхзонная ночь"),
            "tariff.three_zone.peak_price_per_kwh": _normalize_price(tariff_three_peak_price_per_kwh, "Трёхзонный пик"),
            "tariff.three_zone.day_start": _normalize_time(tariff_three_day_start, "Начало дня (3 зоны)"),
            "tariff.three_zone.night_start": _normalize_time(tariff_three_night_start, "Начало ночи (3 зоны)"),
            "tariff.three_zone.peak_morning_start": _normalize_time(tariff_three_peak_morning_start, "Пик 1 старт"),
            "tariff.three_zone.peak_morning_end": _normalize_time(tariff_three_peak_morning_end, "Пик 1 конец"),
            "tariff.three_zone.peak_evening_start": _normalize_time(tariff_three_peak_evening_start, "Пик 2 старт"),
            "tariff.three_zone.peak_evening_end": _normalize_time(tariff_three_peak_evening_end, "Пик 2 конец"),
        }
    except ValueError as exc:
        return RedirectResponse(url=f"/settings?flash={quote_plus(str(exc))}", status_code=303)

    runtime_after, saved_plan = configure_tariff_settings(db, values=values)
    effective_from_label = saved_plan.effective_from_label
    if saved_plan.effective_from == runtime_after.tariff_effective_from:
        flash = f"Тариф сохранён и действует с {effective_from_label}. Разбивка kWh и стоимости считается по выбранным зонам времени."
    else:
        flash = f"Тариф сохранён в расписание с {effective_from_label}. До этой даты расчёты kWh и стоимости идут по текущему тарифу, затем автоматически переключатся."
    return RedirectResponse(url=f"/settings?flash={quote_plus(flash)}", status_code=303)


@router.get("/backups", response_class=HTMLResponse)
def backups_page(request: Request, db: Session = Depends(get_db)):
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="backups", page_title="Резервные копии", runtime=runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "backups": list_backups(),
        }
    )
    return templates.TemplateResponse(request, "backups.html", context)


@router.get("/devices/{device_id}", response_class=HTMLResponse)
def device_detail(device_id: int, request: Request, tab: str = Query(default="overview"), auto_refresh: bool = Query(default=True), db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None or device.is_deleted:
        runtime = get_runtime_config(db)
        return templates.TemplateResponse(request, "not_found.html", _base_context(request=request, active_nav="devices", page_title="Не найдено", runtime=runtime), status_code=404)

    if tab not in {"overview", "charts", "history", "control"}:
        tab = "overview"

    view_model = get_device_dashboard(db, device)
    refresh_seconds = settings.smartlife_sync_interval_seconds if auto_refresh and settings.smartlife_background_sync_enabled else None
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="devices", page_title=device.display_name, refresh_seconds=refresh_seconds, auto_refresh=auto_refresh, runtime=runtime)
    context.update(
        {
            "device": device,
            "daily": view_model["daily"],
            "monthly": view_model["monthly"],
            "snapshots": view_model["snapshots"],
            "device_view": view_model,
            "active_tab": tab,
            "command_logs": get_recent_command_logs(db, device.id, limit=12),
            "auto_refresh": auto_refresh,
            "room_choices": get_room_choices(db),
        }
    )
    return templates.TemplateResponse(request, "device_detail.html", context)


@router.post("/actions/sync-provider")
def sync_provider_action():
    try:
        outcome = run_sync_job(trigger=SyncRunTrigger.MANUAL, fail_if_running=True)
        result = outcome["result"]
        flash = (
            f"Синхронизация завершена: provider={result['provider']} devices={result['devices_total']} "
            f"daily={result['daily_samples_total']} monthly={result['monthly_samples_total']} "
            f"snapshots={result['snapshots_total']} pruned={result.get('pruned_devices_total', 0)} "
            f"aggregated={result['aggregated_energy_updates']} за {outcome['duration_ms']} ms"
        )
    except SyncAlreadyRunningError:
        flash = "Синхронизация уже выполняется в фоне. Подожди завершения текущего цикла."
    except Exception as exc:  # noqa: BLE001
        flash = f"Sync failed: {exc}"
    return RedirectResponse(url=f"/sync?flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/hide")
def hide_device_action(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    flash = "Устройство не найдено."
    if device is not None and not device.is_deleted:
        device.is_hidden = True
        device.hidden_reason = "hidden by user"
        db.commit()
        flash = f"Устройство «{device.display_name}» скрыто из интерфейса."
    return RedirectResponse(url=f"/devices?flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/unhide")
def unhide_device_action(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    flash = "Устройство не найдено."
    if device is not None and not device.is_deleted:
        device.is_hidden = False
        device.hidden_reason = "shown by user"
        db.commit()
        flash = f"Устройство «{device.display_name}» снова показывается в интерфейсе."
    return RedirectResponse(url=f"/devices?include_hidden=1&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/bulk-update")
def bulk_update_devices_action(
    device_ids: list[int] = Form(default=[]),
    bulk_action: str = Form(...),
    room_value: str = Form(default=""),
    db: Session = Depends(get_db),
):
    selected = [db.get(Device, device_id) for device_id in device_ids]
    devices = [device for device in selected if device is not None and not device.is_deleted]
    if not devices:
        return RedirectResponse(url=f"/devices?flash={quote_plus('Ничего не выбрано для массового действия.')}" , status_code=303)

    if bulk_action == "hide":
        for device in devices:
            device.is_hidden = True
            device.hidden_reason = "hidden by user"
        flash = f"Скрыто устройств: {len(devices)}."
    elif bulk_action == "unhide":
        for device in devices:
            device.is_hidden = False
            device.hidden_reason = "shown by user"
        flash = f"Показано устройств: {len(devices)}."
    elif bulk_action == "set_room":
        room_name = room_value.strip()
        if not room_name:
            flash = "Для массового назначения комнаты укажи название комнаты."
            return RedirectResponse(url=f"/devices?include_hidden=1&flash={quote_plus(flash)}", status_code=303)
        for device in devices:
            device.custom_room_name = room_name
        flash = f"Комната «{room_name}» назначена для {len(devices)} устройств."
    elif bulk_action == "clear_room":
        for device in devices:
            device.custom_room_name = None
        flash = f"Локальная комната очищена у {len(devices)} устройств."
    else:
        flash = "Неизвестное массовое действие."
        return RedirectResponse(url=f"/devices?flash={quote_plus(flash)}", status_code=303)

    db.commit()
    return RedirectResponse(url=f"/devices?include_hidden=1&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/save-meta")
def save_device_meta_action(
    device_id: int,
    custom_name: str = Form(default=""),
    custom_room_name: str = Form(default=""),
    notes: str = Form(default=""),
    source_tab: str = Form(default="overview"),
    db: Session = Depends(get_db),
):
    device = db.get(Device, device_id)
    flash = "Устройство не найдено."
    if device is not None and not device.is_deleted:
        device.custom_name = custom_name.strip() or None
        device.custom_room_name = custom_room_name.strip() or None
        device.notes = notes.strip() or None
        db.commit()
        flash = f"Карточка устройства «{device.display_name}» обновлена."
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/toggle")
def toggle_device_action(
    device_id: int,
    desired_state: str = Form(...),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        desired_bool = desired_state.lower() in {"1", "true", "yes", "on"}
        result = set_device_switch_state(db, device_id, desired_bool, trigger=SyncRunTrigger.MANUAL.value)
        flash = (
            f"Команда отправлена: устройство #{result['device_id']} переключено в состояние "
            f"{'вкл' if desired_bool else 'выкл'}."
        )
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)
