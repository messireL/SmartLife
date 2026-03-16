from __future__ import annotations

import json
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutils import format_local_date, format_local_datetime
from app.db.models import Device, DeviceBadge, SyncRun, SyncRunTrigger
from app.db.session import get_db
from app.services.backup_service import list_backups
from app.services.dashboard_service import (
    get_dashboard_panels,
    get_dashboard_summary,
    get_device_dashboard,
    get_sync_overview,
)
from app.services.device_control_service import (
    DeviceControlError,
    get_recent_command_logs,
    set_device_boolean_code_state,
    set_device_enum_code_value,
    set_device_integer_code_value,
    set_device_mode,
    set_device_multiple_switch_codes_state,
    set_device_switch_code_state,
    set_device_switch_state,
    set_device_target_temperature,
)
from app.services.badge_service import ALLOWED_BADGE_COLORS, assign_badge_to_devices, create_badge, delete_badge, get_badge_choices as get_badge_choices_service, list_badges, update_badge
from app.services.channel_style_service import get_channel_icon_choices, get_channel_role_choices, normalize_channel_icon_key, normalize_channel_role_key
from app.services.device_query_service import get_badge_choices, get_devices_for_ui, get_provider_choices, get_room_choices
from app.services.room_service import get_rooms_overview
from app.services.automation_service import (
    WEEKDAY_CHOICES,
    create_automation_rule,
    delete_automation_rule,
    duplicate_automation_rule,
    format_automation_runs,
    get_automation_target_choices,
    list_automation_rules,
    list_recent_automation_runs,
    run_automation_rule_now,
    set_automation_rule_enabled,
    update_automation_rule,
)
from app.services.tuya_scene_service import (
    get_tuya_scene_bridge_overview,
    save_configured_home_ids,
    set_tuya_automation_enabled,
    trigger_tuya_scene,
)
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
from app.services.runtime_diagnostics_service import get_runtime_diagnostics
from app.services.tariff_profile_service import (
    SYSTEM_TARIFF_PROFILE_KEY,
    delete_tariff_profile,
    get_tariff_profile,
    list_tariff_profiles,
    upsert_tariff_profile,
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
    {"key": "badges", "href": "/badges", "label": "Плашки"},
    {"key": "scenarios", "href": "/scenarios", "label": "Сценарии"},
    {"key": "consumption", "href": "/consumption", "label": "Потребление"},
    {"key": "sync", "href": "/sync", "label": "Синхронизация"},
    {"key": "settings", "href": "/settings", "label": "Настройки"},
    {"key": "backups", "href": "/backups", "label": "Резервные копии"},
]


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


def _parse_tariff_form_payload(
    *,
    tariff_mode: str,
    tariff_currency: str,
    tariff_flat_price_per_kwh: str,
    tariff_two_day_price_per_kwh: str,
    tariff_two_night_price_per_kwh: str,
    tariff_two_day_start: str,
    tariff_two_night_start: str,
    tariff_three_day_price_per_kwh: str,
    tariff_three_night_price_per_kwh: str,
    tariff_three_peak_price_per_kwh: str,
    tariff_three_day_start: str,
    tariff_three_night_start: str,
    tariff_three_peak_morning_start: str,
    tariff_three_peak_morning_end: str,
    tariff_three_peak_evening_start: str,
    tariff_three_peak_evening_end: str,
) -> dict[str, str]:
    mode = (tariff_mode or "flat").strip()
    if mode not in {"flat", "two_zone", "three_zone"}:
        raise ValueError("Неизвестный режим тарифа. Используй flat, two_zone или three_zone.")
    return {
        "tariff_mode": mode,
        "tariff_currency": (tariff_currency or "₽").strip() or "₽",
        "tariff_flat_price_per_kwh": _normalize_price(tariff_flat_price_per_kwh, "Единый тариф"),
        "tariff_two_day_price_per_kwh": _normalize_price(tariff_two_day_price_per_kwh, "Двухзонный день"),
        "tariff_two_night_price_per_kwh": _normalize_price(tariff_two_night_price_per_kwh, "Двухзонная ночь"),
        "tariff_two_day_start": _normalize_time(tariff_two_day_start, "Начало дня (2 зоны)"),
        "tariff_two_night_start": _normalize_time(tariff_two_night_start, "Начало ночи (2 зоны)"),
        "tariff_three_day_price_per_kwh": _normalize_price(tariff_three_day_price_per_kwh, "Трёхзонный день"),
        "tariff_three_night_price_per_kwh": _normalize_price(tariff_three_night_price_per_kwh, "Трёхзонная ночь"),
        "tariff_three_peak_price_per_kwh": _normalize_price(tariff_three_peak_price_per_kwh, "Трёхзонный пик"),
        "tariff_three_day_start": _normalize_time(tariff_three_day_start, "Начало дня (3 зоны)"),
        "tariff_three_night_start": _normalize_time(tariff_three_night_start, "Начало ночи (3 зоны)"),
        "tariff_three_peak_morning_start": _normalize_time(tariff_three_peak_morning_start, "Пик 1 старт"),
        "tariff_three_peak_morning_end": _normalize_time(tariff_three_peak_morning_end, "Пик 1 конец"),
        "tariff_three_peak_evening_start": _normalize_time(tariff_three_peak_evening_start, "Пик 2 старт"),
        "tariff_three_peak_evening_end": _normalize_time(tariff_three_peak_evening_end, "Пик 2 конец"),
    }


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
    badge_filter: str = Query(default=""),
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
        badge_filter=badge_filter,
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
                "badge_filter": badge_filter,
            },
            "provider_choices": get_provider_choices(db),
            "room_choices": get_room_choices(db),
            "badge_choices": get_badge_choices(db),
            "hidden_total": len(hidden_total),
            "summary": get_dashboard_summary(db),
        }
    )
    return templates.TemplateResponse(request, "devices.html", context)


@router.get("/badges", response_class=HTMLResponse)
def badges_page(request: Request, db: Session = Depends(get_db)):
    runtime = get_runtime_config(db)
    context = _base_context(request=request, active_nav="badges", page_title="Плашки", runtime=runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "badges": list_badges(db),
            "badge_color_choices": [
                {"value": item, "label": item.capitalize()} for item in sorted(ALLOWED_BADGE_COLORS)
            ],
            "badge_edit_choices": list_badges(db),
        }
    )
    return templates.TemplateResponse(request, "badges.html", context)


@router.post("/badges/create")
def create_badge_action(name: str = Form(...), color: str = Form(default="slate"), db: Session = Depends(get_db)):
    try:
        badge = create_badge(db, name=name, color=color)
        flash = f"Плашка «{badge.name}» создана."
    except ValueError as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/badges?flash={quote_plus(flash)}", status_code=303)


@router.post("/badges/{badge_id}/update")
def update_badge_action(badge_id: int, name: str = Form(...), color: str = Form(default="slate"), db: Session = Depends(get_db)):
    try:
        badge = update_badge(db, badge_id=badge_id, name=name, color=color)
        flash = f"Плашка «{badge.name}» обновлена."
    except ValueError as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/badges?flash={quote_plus(flash)}", status_code=303)


@router.post("/badges/{badge_id}/delete")
def delete_badge_action(badge_id: int, db: Session = Depends(get_db)):
    badge, affected = delete_badge(db, badge_id)
    if badge is None:
        flash = "Плашка не найдена."
    else:
        flash = f"Плашка «{badge.name}» удалена. С устройств снято назначений: {affected}."
    return RedirectResponse(url=f"/badges?flash={quote_plus(flash)}", status_code=303)


def _safe_tuya_scene_bridge_overview(db: Session) -> dict[str, object]:
    try:
        return get_tuya_scene_bridge_overview(db)
    except Exception as exc:
        return {
            "configured_home_ids": [],
            "configured_home_ids_csv": "",
            "homes": [],
            "scene_choices": [],
            "scene_index": {},
            "automation_choices": [],
            "automation_index": {},
            "warnings": [],
            "errors": [f"Tuya scene bridge временно недоступен: {exc}"],
            "is_configured": False,
            "fetched_at": None,
            "homes_count": 0,
            "scenes_count": 0,
            "automations_count": 0,
        }


def _normalize_scenario_query(value: str | None) -> str:
    return (value or "").strip()


def _filter_automation_rules_for_ui(rules: list[dict[str, object]], *, search: str, state_filter: str, kind_filter: str) -> list[dict[str, object]]:
    search_lower = search.lower()
    filtered: list[dict[str, object]] = []
    for item in rules:
        if state_filter == "enabled" and not item.get("is_enabled"):
            continue
        if state_filter == "disabled" and item.get("is_enabled"):
            continue
        if kind_filter != "all" and item.get("action_kind") != kind_filter:
            continue
        haystack = " ".join(
            str(part or "")
            for part in (
                item.get("name"),
                item.get("target_label"),
                item.get("device_name"),
                item.get("notes"),
                item.get("desired_state_label"),
            )
        ).lower()
        if search_lower and search_lower not in haystack:
            continue
        filtered.append(item)
    return filtered


def _filter_automation_runs_for_ui(runs: list[dict[str, object]], *, search: str, status_filter: str) -> list[dict[str, object]]:
    search_lower = search.lower()
    filtered: list[dict[str, object]] = []
    for item in runs:
        if status_filter != "all" and item.get("status") != status_filter:
            continue
        rule = item.get("rule")
        device = item.get("device")
        haystack = " ".join(
            str(part or "")
            for part in (
                getattr(rule, "name", ""),
                getattr(device, "name", ""),
                item.get("result_summary"),
                item.get("error_message"),
                item.get("trigger_label"),
            )
        ).lower()
        if search_lower and search_lower not in haystack:
            continue
        filtered.append(item)
    return filtered


@router.get("/scenarios", response_class=HTMLResponse)
def scenarios_page(
    request: Request,
    scenario_tab: str = Query(default="local"),
    scenario_search: str = Query(default=""),
    scenario_state: str = Query(default="all"),
    scenario_kind: str = Query(default="all"),
    log_status: str = Query(default="all"),
    db: Session = Depends(get_db),
):
    runtime = get_runtime_config(db)
    tuya_scene_bridge = _safe_tuya_scene_bridge_overview(db)
    rules = list_automation_rules(
        db,
        scene_choices=tuya_scene_bridge.get("scene_choices", []),
        automation_choices=tuya_scene_bridge.get("automation_choices", []),
    )
    if scenario_tab not in {"local", "tuya", "log"}:
        scenario_tab = "local"
    scenario_search = _normalize_scenario_query(scenario_search)
    if scenario_state not in {"all", "enabled", "disabled"}:
        scenario_state = "all"
    if scenario_kind not in {"all", "device_switch", "tuya_scene", "tuya_automation"}:
        scenario_kind = "all"
    if log_status not in {"all", "success", "error", "skipped"}:
        log_status = "all"

    filtered_rules = _filter_automation_rules_for_ui(rules, search=scenario_search, state_filter=scenario_state, kind_filter=scenario_kind)
    formatted_runs = format_automation_runs(list_recent_automation_runs(db, limit=40))
    filtered_runs = _filter_automation_runs_for_ui(formatted_runs, search=scenario_search, status_filter=log_status)

    context = _base_context(request=request, active_nav="scenarios", page_title="Сценарии", runtime=runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "automation_rules": filtered_rules,
            "automation_rules_total": len(rules),
            "automation_rules_filtered": len(filtered_rules),
            "automation_target_choices": get_automation_target_choices(db, tuya_bridge=tuya_scene_bridge),
            "automation_runs": filtered_runs,
            "automation_runs_total": len(formatted_runs),
            "automation_runs_filtered": len(filtered_runs),
            "weekday_choices": WEEKDAY_CHOICES,
            "tuya_scene_bridge": tuya_scene_bridge,
            "scenario_tab": scenario_tab,
            "scenario_search": scenario_search,
            "scenario_state": scenario_state,
            "scenario_kind": scenario_kind,
            "log_status": log_status,
            "scenario_filters": {
                "state_choices": [
                    {"value": "all", "label": "Все"},
                    {"value": "enabled", "label": "Только активные"},
                    {"value": "disabled", "label": "Только пауза"},
                ],
                "kind_choices": [
                    {"value": "all", "label": "Все цели"},
                    {"value": "device_switch", "label": "Локальные устройства"},
                    {"value": "tuya_scene", "label": "Tuya Tap-to-Run"},
                    {"value": "tuya_automation", "label": "Tuya Automation"},
                ],
                "log_status_choices": [
                    {"value": "all", "label": "Любой статус"},
                    {"value": "success", "label": "Успех"},
                    {"value": "error", "label": "Ошибки"},
                    {"value": "skipped", "label": "Пропущено"},
                ],
            },
            "automation_summary": {
                "total": len(rules),
                "enabled": len([item for item in rules if item["is_enabled"]]),
                "disabled": len([item for item in rules if not item["is_enabled"]]),
            },
        }
    )
    return templates.TemplateResponse(request, "scenarios.html", context)


@router.post("/scenarios/tuya-scenes/run")
def run_tuya_scene_action(
    home_id: str = Form(...),
    scene_id: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        trigger_tuya_scene(db, home_id=home_id, scene_id=scene_id)
        bridge = get_tuya_scene_bridge_overview(db)
        label = bridge.get("scene_index", {}).get(f"{home_id}:{scene_id}", {}).get("label") or f"Tuya-сцена {scene_id}"
        flash = f"Запущена сцена: {label}"
    except Exception as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


@router.post("/scenarios/tuya-automations/toggle")
def toggle_tuya_automation_action(
    home_id: str = Form(...),
    automation_id: str = Form(...),
    enabled: str = Form(default="1"),
    db: Session = Depends(get_db),
):
    desired_enabled = str(enabled).lower() in {"1", "true", "on", "yes"}
    try:
        set_tuya_automation_enabled(db, home_id=home_id, automation_id=automation_id, enabled=desired_enabled)
        flash = f"Tuya-автоматизация {'включена' if desired_enabled else 'выключена'}."
    except Exception as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


@router.post("/scenarios/create")
def create_scenario_action(
    name: str = Form(default=""),
    target_key: str = Form(...),
    desired_state: str = Form(default="on"),
    schedule_time: str = Form(...),
    weekdays: list[str] = Form(default=[]),
    is_enabled: str = Form(default="1"),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    try:
        rule = create_automation_rule(
            db,
            name=name,
            target_key=target_key,
            desired_state=(desired_state == "on"),
            schedule_time=schedule_time,
            weekdays=weekdays,
            is_enabled=is_enabled.lower() in {"1", "true", "on", "yes"},
            notes=notes,
        )
        flash = f"Сценарий «{rule.name}» создан."
    except ValueError as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


@router.post("/scenarios/{rule_id}/update")
def update_scenario_action(
    rule_id: int,
    name: str = Form(default=""),
    target_key: str = Form(...),
    desired_state: str = Form(default="on"),
    schedule_time: str = Form(...),
    weekdays: list[str] = Form(default=[]),
    is_enabled: str = Form(default="0"),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    try:
        rule = update_automation_rule(
            db,
            rule_id=rule_id,
            name=name,
            target_key=target_key,
            desired_state=(desired_state == "on"),
            schedule_time=schedule_time,
            weekdays=weekdays,
            is_enabled=is_enabled.lower() in {"1", "true", "on", "yes"},
            notes=notes,
        )
        flash = f"Сценарий «{rule.name}» обновлён."
    except ValueError as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


@router.post("/scenarios/{rule_id}/run")
def run_scenario_action(rule_id: int, db: Session = Depends(get_db)):
    try:
        result = run_automation_rule_now(db, rule_id)
        flash = f"Сценарий выполнен: {result['message']}"
    except ValueError as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


@router.post("/scenarios/{rule_id}/toggle-enabled")
def toggle_scenario_enabled_action(
    rule_id: int,
    enabled: str = Form(default="1"),
    db: Session = Depends(get_db),
):
    try:
        rule = set_automation_rule_enabled(db, rule_id, str(enabled).lower() in {"1", "true", "on", "yes"})
        flash = f"Сценарий «{rule.name}» {'включён' if rule.is_enabled else 'поставлен на паузу'}."
    except ValueError as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


@router.post("/scenarios/{rule_id}/duplicate")
def duplicate_scenario_action(rule_id: int, db: Session = Depends(get_db)):
    try:
        rule = duplicate_automation_rule(db, rule_id)
        flash = f"Создана копия сценария: «{rule.name}». Копия стартует в паузе, чтобы не устроить самодеятельность без спроса."
    except ValueError as exc:
        flash = str(exc)
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


@router.post("/scenarios/{rule_id}/delete")
def delete_scenario_action(rule_id: int, db: Session = Depends(get_db)):
    rule = delete_automation_rule(db, rule_id)
    flash = f"Сценарий «{rule.name}» удалён." if rule else "Сценарий не найден."
    return RedirectResponse(url=f"/scenarios?flash={quote_plus(flash)}", status_code=303)


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
def settings_page(request: Request, profile_key: str = Query(default=""), db: Session = Depends(get_db)):
    runtime = get_runtime_config(db)
    tariff_editor_plan = get_tariff_editor_plan(db)
    next_tariff_plan = get_next_scheduled_tariff_plan(db)
    change_target_month = get_tariff_change_target_month()
    diagnostics = get_runtime_diagnostics(db)
    context = _base_context(request=request, active_nav="settings", page_title="Настройки", runtime=runtime)
    tariff_profiles = list_tariff_profiles(db, runtime)
    tariff_profile_edit = get_tariff_profile(db, profile_key, runtime)
    context.update(
        {
            "summary": get_dashboard_summary(db),
            "sync_overview": get_sync_overview(db),
            "diagnostics": diagnostics,
            "tariff_editor_plan": tariff_editor_plan,
            "next_tariff_plan": next_tariff_plan,
            "tariff_change_target_month": change_target_month,
            "tariff_profiles": tariff_profiles,
            "tariff_profile_edit": tariff_profile_edit,
            "tuya_scene_bridge": _safe_tuya_scene_bridge_overview(db),
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




@router.post("/settings/tuya-scenes")
def update_tuya_scene_settings(
    tuya_scene_home_ids: str = Form(default=""),
    db: Session = Depends(get_db),
):
    home_ids = save_configured_home_ids(db, tuya_scene_home_ids)
    flash = (
        f"Список Tuya home_id сохранён: {', '.join(home_ids)}."
        if home_ids
        else "Список Tuya home_id очищен. Мост Tuya-сцен временно не будет ничего показывать."
    )
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
    try:
        parsed = _parse_tariff_form_payload(
            tariff_mode=tariff_mode,
            tariff_currency=tariff_currency,
            tariff_flat_price_per_kwh=tariff_flat_price_per_kwh,
            tariff_two_day_price_per_kwh=tariff_two_day_price_per_kwh,
            tariff_two_night_price_per_kwh=tariff_two_night_price_per_kwh,
            tariff_two_day_start=tariff_two_day_start,
            tariff_two_night_start=tariff_two_night_start,
            tariff_three_day_price_per_kwh=tariff_three_day_price_per_kwh,
            tariff_three_night_price_per_kwh=tariff_three_night_price_per_kwh,
            tariff_three_peak_price_per_kwh=tariff_three_peak_price_per_kwh,
            tariff_three_day_start=tariff_three_day_start,
            tariff_three_night_start=tariff_three_night_start,
            tariff_three_peak_morning_start=tariff_three_peak_morning_start,
            tariff_three_peak_morning_end=tariff_three_peak_morning_end,
            tariff_three_peak_evening_start=tariff_three_peak_evening_start,
            tariff_three_peak_evening_end=tariff_three_peak_evening_end,
        )
        values = {
            "tariff.mode": parsed["tariff_mode"],
            "tariff.currency": parsed["tariff_currency"],
            "tariff.flat.price_per_kwh": parsed["tariff_flat_price_per_kwh"],
            "tariff.two_zone.day_price_per_kwh": parsed["tariff_two_day_price_per_kwh"],
            "tariff.two_zone.night_price_per_kwh": parsed["tariff_two_night_price_per_kwh"],
            "tariff.two_zone.day_start": parsed["tariff_two_day_start"],
            "tariff.two_zone.night_start": parsed["tariff_two_night_start"],
            "tariff.three_zone.day_price_per_kwh": parsed["tariff_three_day_price_per_kwh"],
            "tariff.three_zone.night_price_per_kwh": parsed["tariff_three_night_price_per_kwh"],
            "tariff.three_zone.peak_price_per_kwh": parsed["tariff_three_peak_price_per_kwh"],
            "tariff.three_zone.day_start": parsed["tariff_three_day_start"],
            "tariff.three_zone.night_start": parsed["tariff_three_night_start"],
            "tariff.three_zone.peak_morning_start": parsed["tariff_three_peak_morning_start"],
            "tariff.three_zone.peak_morning_end": parsed["tariff_three_peak_morning_end"],
            "tariff.three_zone.peak_evening_start": parsed["tariff_three_peak_evening_start"],
            "tariff.three_zone.peak_evening_end": parsed["tariff_three_peak_evening_end"],
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


@router.post("/settings/tariff-profiles/save")
def save_tariff_profile_settings(
    profile_key: str = Form(default=""),
    profile_name: str = Form(default=""),
    profile_note: str = Form(default=""),
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
    runtime = get_runtime_config(db)
    try:
        parsed = _parse_tariff_form_payload(
            tariff_mode=tariff_mode,
            tariff_currency=tariff_currency,
            tariff_flat_price_per_kwh=tariff_flat_price_per_kwh,
            tariff_two_day_price_per_kwh=tariff_two_day_price_per_kwh,
            tariff_two_night_price_per_kwh=tariff_two_night_price_per_kwh,
            tariff_two_day_start=tariff_two_day_start,
            tariff_two_night_start=tariff_two_night_start,
            tariff_three_day_price_per_kwh=tariff_three_day_price_per_kwh,
            tariff_three_night_price_per_kwh=tariff_three_night_price_per_kwh,
            tariff_three_peak_price_per_kwh=tariff_three_peak_price_per_kwh,
            tariff_three_day_start=tariff_three_day_start,
            tariff_three_night_start=tariff_three_night_start,
            tariff_three_peak_morning_start=tariff_three_peak_morning_start,
            tariff_three_peak_morning_end=tariff_three_peak_morning_end,
            tariff_three_peak_evening_start=tariff_three_peak_evening_start,
            tariff_three_peak_evening_end=tariff_three_peak_evening_end,
        )
        profile = upsert_tariff_profile(
            db,
            runtime,
            {
                **parsed,
                "profile_key": profile_key,
                "profile_name": profile_name,
                "profile_note": profile_note,
            },
        )
    except ValueError as exc:
        return RedirectResponse(url=f"/settings?flash={quote_plus(str(exc))}", status_code=303)

    flash = f"Тарифный профиль «{profile['name']}» сохранён. Его уже можно назначать устройствам из карточки."
    return RedirectResponse(url=f"/settings?flash={quote_plus(flash)}&profile_key={quote_plus(profile['key'])}", status_code=303)


@router.post("/settings/tariff-profiles/delete")
def delete_tariff_profile_settings(profile_key: str = Form(default=""), db: Session = Depends(get_db)):
    runtime = get_runtime_config(db)
    deleted = delete_tariff_profile(db, runtime, profile_key)
    flash = "Тарифный профиль не найден."
    if deleted:
        flash = "Тарифный профиль удалён. Устройства, которые были к нему привязаны, возвращены на системный тариф."
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
def device_detail(device_id: int, request: Request, tab: str = Query(default="overview"), section: str = Query(default="summary"), auto_refresh: bool = Query(default=True), db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None or device.is_deleted:
        runtime = get_runtime_config(db)
        return templates.TemplateResponse(request, "not_found.html", _base_context(request=request, active_nav="devices", page_title="Не найдено", runtime=runtime), status_code=404)

    if tab not in {"overview", "charts", "history", "control", "local"}:
        tab = "overview"
    if section not in {"summary", "channels", "energy", "passport", "snapshots"}:
        section = "summary"

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
            "active_overview_section": section,
            "command_logs": get_recent_command_logs(db, device.id, limit=12),
            "auto_refresh": auto_refresh,
            "room_choices": get_room_choices(db),
            "badge_choices": get_badge_choices_service(db),
            "tariff_profile_choices": list_tariff_profiles(db, runtime),
            "system_tariff_profile_key": SYSTEM_TARIFF_PROFILE_KEY,
            "channel_role_choices": get_channel_role_choices(),
            "channel_icon_choices": get_channel_icon_choices(),
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
    badge_id: str = Form(default=""),
    db: Session = Depends(get_db),
):
    selected = [db.get(Device, device_id) for device_id in device_ids]
    devices = [device for device in selected if device is not None and not device.is_deleted]
    if not devices:
        return RedirectResponse(url=f"/devices?flash={quote_plus('Ничего не выбрано для массового действия.')}", status_code=303)

    if bulk_action == "hide":
        for device in devices:
            device.is_hidden = True
            device.hidden_reason = "hidden by user"
        db.commit()
        flash = f"Скрыто устройств: {len(devices)}."
    elif bulk_action == "unhide":
        for device in devices:
            device.is_hidden = False
            device.hidden_reason = "shown by user"
        db.commit()
        flash = f"Показано устройств: {len(devices)}."
    elif bulk_action == "set_room":
        room_name = room_value.strip()
        if not room_name:
            flash = "Для массового назначения комнаты укажи название комнаты."
            return RedirectResponse(url=f"/devices?include_hidden=1&flash={quote_plus(flash)}", status_code=303)
        for device in devices:
            device.custom_room_name = room_name
        db.commit()
        flash = f"Комната «{room_name}» назначена для {len(devices)} устройств."
    elif bulk_action == "clear_room":
        for device in devices:
            device.custom_room_name = None
        db.commit()
        flash = f"Локальная комната очищена у {len(devices)} устройств."
    elif bulk_action == "set_badge":
        if not badge_id.isdigit():
            flash = "Для массового назначения выбери плашку."
            return RedirectResponse(url=f"/devices?include_hidden=1&flash={quote_plus(flash)}", status_code=303)
        badge = db.get(DeviceBadge, int(badge_id))
        if badge is None:
            flash = "Выбранная плашка не найдена."
            return RedirectResponse(url=f"/devices?include_hidden=1&flash={quote_plus(flash)}", status_code=303)
        assign_badge_to_devices(db, devices, badge.id)
        flash = f"Плашка «{badge.name}» назначена для {len(devices)} устройств."
    elif bulk_action == "clear_badge":
        assign_badge_to_devices(db, devices, None)
        flash = f"Плашки сняты у {len(devices)} устройств."
    else:
        flash = "Неизвестное массовое действие."
        return RedirectResponse(url=f"/devices?flash={quote_plus(flash)}", status_code=303)

    return RedirectResponse(url=f"/devices?include_hidden=1&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/save-meta")
async def save_device_meta_action(
    request: Request,
    device_id: int,
    custom_name: str = Form(default=""),
    custom_room_name: str = Form(default=""),
    notes: str = Form(default=""),
    badge_id: str = Form(default=""),
    tariff_profile_key: str = Form(default=""),
    source_tab: str = Form(default="overview"),
    db: Session = Depends(get_db),
):
    device = db.get(Device, device_id)
    flash = "Устройство не найдено."
    if device is not None and not device.is_deleted:
        form = await request.form()
        channel_aliases: dict[str, str] = {}
        channel_roles: dict[str, str] = {}
        channel_icons: dict[str, str] = {}
        has_channel_alias_inputs = False
        has_channel_role_inputs = False
        has_channel_icon_inputs = False
        for key, value in form.multi_items():
            if key.startswith("channel_alias__"):
                has_channel_alias_inputs = True
                code = key.removeprefix("channel_alias__").strip()
                alias = str(value or "").strip()
                if code and alias:
                    channel_aliases[code] = alias
                continue
            if key.startswith("channel_role__"):
                has_channel_role_inputs = True
                code = key.removeprefix("channel_role__").strip()
                role_key = normalize_channel_role_key(str(value or "").strip())
                if code and role_key:
                    channel_roles[code] = role_key
                continue
            if key.startswith("channel_icon__"):
                has_channel_icon_inputs = True
                code = key.removeprefix("channel_icon__").strip()
                icon_key = normalize_channel_icon_key(str(value or "").strip())
                if code and icon_key != "auto":
                    channel_icons[code] = icon_key
        device.custom_name = custom_name.strip() or None
        device.custom_room_name = custom_room_name.strip() or None
        device.notes = notes.strip() or None
        device.badge_id = int(badge_id) if badge_id.isdigit() else None
        selected_profile_key = (tariff_profile_key or "").strip()
        valid_profile_keys = {item["key"] for item in list_tariff_profiles(db, get_runtime_config(db)) if not item.get("is_system")}
        device.tariff_profile_key = selected_profile_key if selected_profile_key in valid_profile_keys else None
        if has_channel_alias_inputs:
            device.channel_aliases_json = json.dumps(channel_aliases, ensure_ascii=False, sort_keys=True) if channel_aliases else None
        if has_channel_role_inputs:
            device.channel_roles_json = json.dumps(channel_roles, ensure_ascii=False, sort_keys=True) if channel_roles else None
        if has_channel_icon_inputs:
            device.channel_icons_json = json.dumps(channel_icons, ensure_ascii=False, sort_keys=True) if channel_icons else None
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




@router.post("/devices/{device_id}/toggle-channel")
def toggle_device_channel_action(
    device_id: int,
    command_code: str = Form(...),
    desired_state: str = Form(...),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        desired_bool = desired_state.lower() in {"1", "true", "yes", "on"}
        result = set_device_switch_code_state(db, device_id, command_code, desired_bool, trigger=SyncRunTrigger.MANUAL.value)
        flash = f"Канал {result['command_code']} переведён в состояние {'вкл' if desired_bool else 'выкл'}."
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/toggle-channel-group")
def toggle_device_channel_group_action(
    device_id: int,
    command_codes: str = Form(...),
    desired_state: str = Form(...),
    group_label: str = Form(default="Группа каналов"),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        codes = [item.strip() for item in (command_codes or '').split(',') if item.strip()]
        desired_bool = desired_state.lower() in {"1", "true", "yes", "on"}
        result = set_device_multiple_switch_codes_state(db, device_id, codes, desired_bool, trigger=SyncRunTrigger.MANUAL.value)
        if result['error_count']:
            errors_text = "; ".join(result['errors'])
            flash = (
                f"{group_label}: выполнено {result['success_count']} команд, ошибок {result['error_count']}. "
                f"{errors_text}"
            )
        else:
            flash = (
                f"{group_label}: {result['success_count']} канал(ов) переведены в состояние "
                f"{'вкл' if desired_bool else 'выкл'}."
            )
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/set-boolean-code")
def set_device_boolean_code_action(
    device_id: int,
    command_code: str = Form(...),
    desired_state: str = Form(...),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        desired_bool = desired_state.lower() in {"1", "true", "yes", "on"}
        result = set_device_boolean_code_state(db, device_id, command_code, desired_bool, trigger=SyncRunTrigger.MANUAL.value)
        flash = f"Параметр {result['command_code']} обновлён: {'вкл' if desired_bool else 'выкл'}."
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/set-enum-code")
def set_device_enum_code_action(
    device_id: int,
    command_code: str = Form(...),
    desired_value: str = Form(...),
    allowed_values: str = Form(default=""),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        allowed = [item.strip() for item in (allowed_values or '').split(',') if item.strip()]
        result = set_device_enum_code_value(db, device_id, command_code, desired_value, allowed_values=allowed, trigger=SyncRunTrigger.MANUAL.value)
        flash = f"Параметр {result['command_code']} обновлён: {result['value']}."
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/set-integer-code")
def set_device_integer_code_action(
    device_id: int,
    command_code: str = Form(...),
    desired_value: str = Form(...),
    minimum: str = Form(default=""),
    maximum: str = Form(default=""),
    step: str = Form(default=""),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        def _maybe_int(value: str) -> int | None:
            value = (value or '').strip()
            return int(value) if value else None
        result = set_device_integer_code_value(
            db,
            device_id,
            command_code,
            desired_value,
            minimum=_maybe_int(minimum),
            maximum=_maybe_int(maximum),
            step=_maybe_int(step),
            trigger=SyncRunTrigger.MANUAL.value,
        )
        flash = f"Параметр {result['command_code']} обновлён: {result['value']}."
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)

@router.post("/devices/{device_id}/set-mode")
def set_device_mode_action(
    device_id: int,
    desired_mode: str = Form(...),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        result = set_device_mode(db, device_id, desired_mode, trigger=SyncRunTrigger.MANUAL.value)
        flash = f"Режим обновлён: устройство #{result['device_id']} переведено в {result['operation_mode']}."
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)


@router.post("/devices/{device_id}/set-temperature")
def set_device_temperature_action(
    device_id: int,
    desired_temperature: str = Form(...),
    source_tab: str = Form(default="control"),
    db: Session = Depends(get_db),
):
    try:
        result = set_device_target_temperature(db, device_id, desired_temperature, trigger=SyncRunTrigger.MANUAL.value)
        flash = f"Целевая температура обновлена: устройство #{result['device_id']} теперь держит {result['target_temperature_c']} °C."
    except DeviceControlError as exc:
        flash = f"Команда не выполнена: {exc}"
    return RedirectResponse(url=f"/devices/{device_id}?tab={quote_plus(source_tab)}&flash={quote_plus(flash)}", status_code=303)
