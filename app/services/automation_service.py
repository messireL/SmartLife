from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.timeutils import get_app_timezone
from app.db.models import AutomationRule, AutomationRunLog, Device
from app.db.session import SessionLocal
from app.services.device_control_service import DeviceControlError, set_device_switch_code_state
from app.services.tuya_scene_service import (
    get_tuya_automation_choices,
    get_tuya_scene_choices,
    set_tuya_automation_enabled,
    trigger_tuya_scene,
)

WEEKDAY_CHOICES = [
    {"value": "1", "label": "Пн"},
    {"value": "2", "label": "Вт"},
    {"value": "3", "label": "Ср"},
    {"value": "4", "label": "Чт"},
    {"value": "5", "label": "Пт"},
    {"value": "6", "label": "Сб"},
    {"value": "7", "label": "Вс"},
]

DEVICE_SWITCH_KIND = "device_switch"
TUYA_SCENE_KIND = "tuya_scene"
TUYA_AUTOMATION_KIND = "tuya_automation"

RUN_STATUS_META = {
    "success": {"label": "успех", "badge": "online"},
    "error": {"label": "ошибка", "badge": "error"},
    "skipped": {"label": "пропущен", "badge": "idle"},
}

RUN_TRIGGER_META = {
    "manual": "ручной запуск",
    "schedule": "по расписанию",
}


def _is_switch_like_code(code: str | None) -> bool:
    if not code:
        return False
    if code in {"switch", "switch_usb"}:
        return True
    if code.startswith("switch_") and code[7:].isdigit():
        return True
    if code.startswith("switch_usb") and code[10:].isdigit():
        return True
    return False


def _label_for_switch_code(device: Device, code: str) -> str:
    alias = device.channel_aliases.get(code)
    if alias:
        return alias
    if code == "switch":
        return "Главное питание"
    if code == "switch_usb":
        return "USB блок"
    if code.startswith("switch_usb") and code[10:].isdigit():
        idx = code[10:]
        return f"USB {idx}"
    if code.startswith("switch_") and code[7:].isdigit():
        idx = code[7:]
        return f"Розетка {idx}"
    return code


def _normalize_time(raw: str) -> str:
    value = (raw or "").strip()
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError("Время должно быть в формате ЧЧ:ММ, например 23:15.") from exc
    return parsed.strftime("%H:%M")


def _normalize_weekdays(values: Iterable[str]) -> str:
    normalized = sorted({str(item).strip() for item in values if str(item).strip() in {str(i) for i in range(1, 8)}})
    if not normalized:
        raise ValueError("Выбери хотя бы один день недели.")
    return ",".join(normalized)


def _parse_target_key(raw: str) -> dict[str, str | int]:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Нужно выбрать конкретное устройство, канал, Tuya-сцену или Tuya-автоматизацию.")
    parts = value.split(":")
    if parts[0] == "scene" and len(parts) >= 3:
        home_id = parts[1].strip()
        scene_id = ":".join(parts[2:]).strip()
        if not home_id or not scene_id:
            raise ValueError("Некорректная Tuya-сцена в цели сценария.")
        return {"kind": TUYA_SCENE_KIND, "home_id": home_id, "scene_id": scene_id}
    if parts[0] == "automation" and len(parts) >= 3:
        home_id = parts[1].strip()
        automation_id = ":".join(parts[2:]).strip()
        if not home_id or not automation_id:
            raise ValueError("Некорректная Tuya-автоматизация в цели сценария.")
        return {"kind": TUYA_AUTOMATION_KIND, "home_id": home_id, "automation_id": automation_id}
    if parts[0] == "device" and len(parts) >= 3:
        device_raw = parts[1].strip()
        code = ":".join(parts[2:]).strip()
    elif len(parts) >= 2:
        device_raw = parts[0].strip()
        code = ":".join(parts[1:]).strip()
    else:
        raise ValueError("Нужно выбрать конкретное устройство или канал.")
    if not device_raw.isdigit():
        raise ValueError("Некорректное устройство в цели сценария.")
    if not _is_switch_like_code(code):
        raise ValueError("Сценарий пока умеет работать только с выключателями, каналами питания, Tuya-сценами и Tuya-автоматизациями.")
    return {"kind": DEVICE_SWITCH_KIND, "device_id": int(device_raw), "code": code}


def _rule_target_label_device(device: Device, code: str) -> str:
    return f"{device.display_name} · {_label_for_switch_code(device, code)}"


def _rule_target_label_scene(home_id: str | None, scene_id: str | None, scene_choices: list[dict] | None = None) -> str:
    key = f"{home_id}:{scene_id}"
    if scene_choices:
        for item in scene_choices:
            if item.get("home_id") == home_id and item.get("scene_id") == scene_id:
                return str(item.get("label") or item.get("scene_name") or key)
    return f"Tuya-сцена · {key}"


def _rule_target_label_automation(home_id: str | None, automation_id: str | None, automation_choices: list[dict] | None = None) -> str:
    key = f"{home_id}:{automation_id}"
    if automation_choices:
        for item in automation_choices:
            if item.get("home_id") == home_id and item.get("automation_id") == automation_id:
                return str(item.get("label") or item.get("automation_name") or key)
    return f"Tuya-автоматизация · {key}"


def _hydrate_rule(
    rule: AutomationRule,
    *,
    scene_choices: list[dict] | None = None,
    automation_choices: list[dict] | None = None,
) -> dict[str, Any]:
    weekdays_set = set(rule.weekdays)
    next_run = get_rule_next_run(rule)
    if rule.action_kind == TUYA_SCENE_KIND:
        target_label = _rule_target_label_scene(rule.tuya_home_id, rule.tuya_scene_id, scene_choices)
        desired_state_label = "запустить сцену"
        device_name = "Tuya-сцена"
        device_badge = None
        target_code = rule.tuya_scene_id or rule.command_code
    elif rule.action_kind == TUYA_AUTOMATION_KIND:
        target_label = _rule_target_label_automation(rule.tuya_home_id, rule.tuya_scene_id, automation_choices)
        desired_state_label = "включить автоматизацию" if rule.desired_state else "выключить автоматизацию"
        device_name = "Tuya-автоматизация"
        device_badge = None
        target_code = rule.tuya_scene_id or rule.command_code
    else:
        target_label = _rule_target_label_device(rule.device, rule.command_code) if rule.device else rule.command_code
        desired_state_label = "включить" if rule.desired_state else "выключить"
        device_name = rule.device.display_name if rule.device else "Устройство удалено"
        device_badge = rule.device.badge.name if rule.device and rule.device.badge else None
        target_code = rule.command_code
    return {
        "id": rule.id,
        "name": rule.name,
        "action_kind": rule.action_kind,
        "device_id": rule.device_id,
        "device_name": device_name,
        "device_badge": device_badge,
        "target_code": target_code,
        "target_label": target_label,
        "desired_state": rule.desired_state,
        "desired_state_label": desired_state_label,
        "schedule_time": rule.schedule_time,
        "weekdays": rule.weekdays,
        "weekdays_set": weekdays_set,
        "weekdays_label": ", ".join(item["label"] for item in WEEKDAY_CHOICES if item["value"] in weekdays_set),
        "is_enabled": rule.is_enabled,
        "notes": rule.notes,
        "last_run_at": rule.last_run_at,
        "last_run_status": rule.last_run_status,
        "last_run_status_label": RUN_STATUS_META.get(rule.last_run_status or "", {}).get("label", rule.last_run_status or "ещё не запускался"),
        "last_run_status_badge": RUN_STATUS_META.get(rule.last_run_status or "", {}).get("badge", "idle"),
        "last_result_summary": rule.last_result_summary,
        "next_run_local": next_run,
        "next_run_label": next_run.strftime("%d-%m-%Y %H:%M") if next_run else "—",
        "tuya_home_id": rule.tuya_home_id,
        "tuya_scene_id": rule.tuya_scene_id,
    }


def list_automation_rules(
    db: Session,
    *,
    scene_choices: list[dict] | None = None,
    automation_choices: list[dict] | None = None,
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(AutomationRule)
        .options(joinedload(AutomationRule.device).joinedload(Device.badge))
        .order_by(AutomationRule.is_enabled.desc(), AutomationRule.schedule_time.asc(), AutomationRule.name.asc())
    ).scalars().all()
    return [_hydrate_rule(item, scene_choices=scene_choices, automation_choices=automation_choices) for item in rows]


def list_recent_automation_runs(db: Session, limit: int = 30) -> list[AutomationRunLog]:
    limit = max(1, min(limit, 100))
    return db.execute(
        select(AutomationRunLog)
        .options(joinedload(AutomationRunLog.rule), joinedload(AutomationRunLog.device))
        .order_by(AutomationRunLog.requested_at.desc(), AutomationRunLog.id.desc())
        .limit(limit)
    ).scalars().all()


def format_automation_runs(rows: list[AutomationRunLog]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for item in rows:
        status_meta = RUN_STATUS_META.get(item.status or "", {})
        formatted.append(
            {
                "id": item.id,
                "requested_at": item.requested_at,
                "rule": item.rule,
                "device": item.device,
                "trigger": item.trigger,
                "trigger_label": RUN_TRIGGER_META.get(item.trigger or "", item.trigger or "—"),
                "status": item.status,
                "status_label": status_meta.get("label", item.status or "—"),
                "status_badge": status_meta.get("badge", "idle"),
                "result_summary": item.result_summary,
                "error_message": item.error_message,
            }
        )
    return formatted


def get_automation_target_choices(db: Session, *, tuya_bridge: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    devices = db.execute(
        select(Device)
        .where(Device.is_deleted.is_(False), Device.is_hidden.is_(False))
        .order_by(Device.custom_room_name.asc().nulls_last(), Device.room_name.asc().nulls_last(), Device.name.asc())
    ).scalars().all()
    choices: list[dict[str, Any]] = []
    for device in devices:
        codes = sorted({code for code in device.control_codes if _is_switch_like_code(code)})
        for code in codes:
            choices.append(
                {
                    "value": f"device:{device.id}:{code}",
                    "device_id": device.id,
                    "code": code,
                    "action_kind": DEVICE_SWITCH_KIND,
                    "label": _rule_target_label_device(device, code),
                    "room": device.display_room_name or "Без комнаты",
                    "device_name": device.display_name,
                    "channel_name": _label_for_switch_code(device, code),
                }
            )
    scene_choices = tuya_bridge.get("scene_choices", []) if tuya_bridge else get_tuya_scene_choices(db)
    automation_choices = tuya_bridge.get("automation_choices", []) if tuya_bridge else get_tuya_automation_choices(db)
    choices.extend(
        {
            **item,
            "action_kind": TUYA_SCENE_KIND,
            "device_id": None,
            "code": item["scene_id"],
            "room": item["home_name"],
            "device_name": item["home_name"],
            "channel_name": item["scene_name"],
        }
        for item in scene_choices
    )
    choices.extend(
        {
            **item,
            "action_kind": TUYA_AUTOMATION_KIND,
            "device_id": None,
            "code": item["automation_id"],
            "room": item["home_name"],
            "device_name": item["home_name"],
            "channel_name": item["automation_name"],
        }
        for item in automation_choices
    )
    return choices


def create_automation_rule(
    db: Session,
    *,
    name: str,
    target_key: str,
    desired_state: bool,
    schedule_time: str,
    weekdays: Iterable[str],
    is_enabled: bool,
    notes: str = "",
) -> AutomationRule:
    target = _parse_target_key(target_key)
    rule = AutomationRule(
        name=(name or "").strip(),
        schedule_time=_normalize_time(schedule_time),
        weekdays_csv=_normalize_weekdays(weekdays),
        is_enabled=bool(is_enabled),
        notes=(notes or "").strip() or None,
    )
    if target["kind"] == DEVICE_SWITCH_KIND:
        device_id = int(target["device_id"])
        command_code = str(target["code"])
        device = db.get(Device, device_id)
        if device is None or device.is_deleted:
            raise ValueError("Устройство для сценария не найдено.")
        if command_code not in set(device.control_codes):
            raise ValueError("Это устройство больше не отдаёт выбранный канал управления.")
        rule.action_kind = DEVICE_SWITCH_KIND
        rule.device_id = device.id
        rule.command_code = command_code
        rule.desired_state = bool(desired_state)
        rule.name = rule.name or _rule_target_label_device(device, command_code)
    elif target["kind"] == TUYA_AUTOMATION_KIND:
        home_id = str(target["home_id"])
        automation_id = str(target["automation_id"])
        automation_choices = get_tuya_automation_choices(db)
        label = _rule_target_label_automation(home_id, automation_id, automation_choices)
        rule.action_kind = TUYA_AUTOMATION_KIND
        rule.device_id = None
        rule.command_code = "automation_toggle"
        rule.desired_state = bool(desired_state)
        rule.tuya_home_id = home_id
        rule.tuya_scene_id = automation_id
        rule.name = rule.name or label
    else:
        home_id = str(target["home_id"])
        scene_id = str(target["scene_id"])
        scene_choices = get_tuya_scene_choices(db)
        label = _rule_target_label_scene(home_id, scene_id, scene_choices)
        rule.action_kind = TUYA_SCENE_KIND
        rule.device_id = None
        rule.command_code = "scene_trigger"
        rule.desired_state = True
        rule.tuya_home_id = home_id
        rule.tuya_scene_id = scene_id
        rule.name = rule.name or label
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_automation_rule(
    db: Session,
    *,
    rule_id: int,
    name: str,
    target_key: str,
    desired_state: bool,
    schedule_time: str,
    weekdays: Iterable[str],
    is_enabled: bool,
    notes: str = "",
) -> AutomationRule:
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise ValueError("Сценарий не найден.")
    target = _parse_target_key(target_key)
    rule.schedule_time = _normalize_time(schedule_time)
    rule.weekdays_csv = _normalize_weekdays(weekdays)
    rule.is_enabled = bool(is_enabled)
    rule.notes = (notes or "").strip() or None
    if target["kind"] == DEVICE_SWITCH_KIND:
        device_id = int(target["device_id"])
        command_code = str(target["code"])
        device = db.get(Device, device_id)
        if device is None or device.is_deleted:
            raise ValueError("Устройство для сценария не найдено.")
        if command_code not in set(device.control_codes):
            raise ValueError("Это устройство больше не отдаёт выбранный канал управления.")
        rule.action_kind = DEVICE_SWITCH_KIND
        rule.device_id = device.id
        rule.command_code = command_code
        rule.desired_state = bool(desired_state)
        rule.tuya_home_id = None
        rule.tuya_scene_id = None
        rule.name = (name or "").strip() or _rule_target_label_device(device, command_code)
    elif target["kind"] == TUYA_AUTOMATION_KIND:
        home_id = str(target["home_id"])
        automation_id = str(target["automation_id"])
        automation_choices = get_tuya_automation_choices(db)
        label = _rule_target_label_automation(home_id, automation_id, automation_choices)
        rule.action_kind = TUYA_AUTOMATION_KIND
        rule.device_id = None
        rule.command_code = "automation_toggle"
        rule.desired_state = bool(desired_state)
        rule.tuya_home_id = home_id
        rule.tuya_scene_id = automation_id
        rule.name = (name or "").strip() or label
    else:
        home_id = str(target["home_id"])
        scene_id = str(target["scene_id"])
        scene_choices = get_tuya_scene_choices(db)
        label = _rule_target_label_scene(home_id, scene_id, scene_choices)
        rule.action_kind = TUYA_SCENE_KIND
        rule.device_id = None
        rule.command_code = "scene_trigger"
        rule.desired_state = True
        rule.tuya_home_id = home_id
        rule.tuya_scene_id = scene_id
        rule.name = (name or "").strip() or label
    db.commit()
    db.refresh(rule)
    return rule


def delete_automation_rule(db: Session, rule_id: int) -> AutomationRule | None:
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        return None
    db.delete(rule)
    db.commit()
    return rule


def set_automation_rule_enabled(db: Session, rule_id: int, enabled: bool) -> AutomationRule:
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise ValueError("Сценарий не найден.")
    rule.is_enabled = bool(enabled)
    db.commit()
    db.refresh(rule)
    return rule


def duplicate_automation_rule(db: Session, rule_id: int) -> AutomationRule:
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise ValueError("Сценарий не найден.")
    duplicate = AutomationRule(
        name=f"{rule.name} (копия)",
        device_id=rule.device_id,
        command_code=rule.command_code,
        action_kind=rule.action_kind,
        tuya_home_id=rule.tuya_home_id,
        tuya_scene_id=rule.tuya_scene_id,
        desired_state=rule.desired_state,
        schedule_time=rule.schedule_time,
        weekdays_csv=rule.weekdays_csv,
        is_enabled=False,
        notes=rule.notes,
        last_trigger_slot=None,
        last_run_at=None,
        last_run_status=None,
        last_result_summary=None,
    )
    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)
    return duplicate


def _log_rule_run(
    db: Session,
    *,
    rule: AutomationRule,
    trigger: str,
    status: str,
    result_summary: str | None = None,
    error_message: str | None = None,
) -> AutomationRunLog:
    log = AutomationRunLog(
        rule_id=rule.id,
        device_id=rule.device_id,
        trigger=trigger,
        status=status,
        requested_at=datetime.utcnow().replace(microsecond=0),
        result_summary=result_summary,
        error_message=error_message,
    )
    db.add(log)
    rule.last_run_at = log.requested_at
    rule.last_run_status = status
    rule.last_result_summary = result_summary or error_message
    return log


def execute_automation_rule(db: Session, rule: AutomationRule, *, trigger: str, slot_key: str | None = None) -> dict[str, str | None]:
    summary = ""
    if rule.action_kind == TUYA_SCENE_KIND:
        try:
            trigger_tuya_scene(db, home_id=rule.tuya_home_id or "", scene_id=rule.tuya_scene_id or "")
            summary = _rule_target_label_scene(rule.tuya_home_id, rule.tuya_scene_id)
            _log_rule_run(db, rule=rule, trigger=trigger, status="success", result_summary=f"{summary} → запуск")
        except Exception as exc:
            summary = str(exc)
            _log_rule_run(db, rule=rule, trigger=trigger, status="error", error_message=summary)
        if slot_key:
            rule.last_trigger_slot = slot_key
        db.commit()
        return {"status": rule.last_run_status, "message": summary}

    if rule.action_kind == TUYA_AUTOMATION_KIND:
        try:
            set_tuya_automation_enabled(
                db,
                home_id=rule.tuya_home_id or "",
                automation_id=rule.tuya_scene_id or "",
                enabled=bool(rule.desired_state),
            )
            summary = _rule_target_label_automation(rule.tuya_home_id, rule.tuya_scene_id)
            suffix = "включить" if rule.desired_state else "выключить"
            _log_rule_run(db, rule=rule, trigger=trigger, status="success", result_summary=f"{summary} → {suffix}")
        except Exception as exc:
            summary = str(exc)
            _log_rule_run(db, rule=rule, trigger=trigger, status="error", error_message=summary)
        if slot_key:
            rule.last_trigger_slot = slot_key
        db.commit()
        return {"status": rule.last_run_status, "message": summary}

    device = db.get(Device, rule.device_id)
    if device is None or device.is_deleted:
        _log_rule_run(db, rule=rule, trigger=trigger, status="error", error_message="Устройство больше не найдено.")
        if slot_key:
            rule.last_trigger_slot = slot_key
        db.commit()
        return {"status": "error", "message": "Устройство больше не найдено."}
    try:
        result = set_device_switch_code_state(
            db,
            device.id,
            rule.command_code,
            rule.desired_state,
            trigger=trigger,
        )
        summary = f"{device.display_name} · {result['command_code']} → {'вкл' if rule.desired_state else 'выкл'}"
        _log_rule_run(db, rule=rule, trigger=trigger, status="success", result_summary=summary)
    except DeviceControlError as exc:
        _log_rule_run(db, rule=rule, trigger=trigger, status="error", error_message=str(exc))
        summary = str(exc)
    if slot_key:
        rule.last_trigger_slot = slot_key
    db.commit()
    return {"status": rule.last_run_status, "message": summary}


def run_automation_rule_now(db: Session, rule_id: int) -> dict[str, str | None]:
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise ValueError("Сценарий не найден.")
    return execute_automation_rule(db, rule, trigger="manual")


def get_rule_next_run(rule: AutomationRule, *, now_local: datetime | None = None) -> datetime | None:
    if not rule.is_enabled:
        return None
    now_local = now_local or datetime.now(get_app_timezone())
    weekdays = {int(item) for item in rule.weekdays if str(item).isdigit()}
    if not weekdays:
        return None
    hh, mm = [int(item) for item in rule.schedule_time.split(":", 1)]
    for offset in range(0, 8):
        candidate = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=offset)
        if candidate.isoweekday() not in weekdays:
            continue
        if offset == 0 and candidate <= now_local:
            continue
        return candidate
    return None


def execute_due_automation_rules(db: Session, *, now_local: datetime | None = None) -> dict[str, int | str]:
    now_local = now_local or datetime.now(get_app_timezone())
    slot_hhmm = now_local.strftime("%H:%M")
    slot_key = now_local.strftime("%Y-%m-%d %H:%M")
    weekday = str(now_local.isoweekday())
    rules = db.execute(
        select(AutomationRule)
        .where(AutomationRule.is_enabled.is_(True), AutomationRule.schedule_time == slot_hhmm)
        .order_by(AutomationRule.id.asc())
    ).scalars().all()
    matched = 0
    executed = 0
    errors = 0
    for rule in rules:
        if weekday not in set(rule.weekdays):
            continue
        matched += 1
        if rule.last_trigger_slot == slot_key:
            continue
        result = execute_automation_rule(db, rule, trigger="schedule", slot_key=slot_key)
        executed += 1
        if result["status"] != "success":
            errors += 1
    return {
        "matched": matched,
        "executed": executed,
        "errors": errors,
        "slot": slot_key,
    }


def run_due_automation_cycle() -> dict[str, int | str]:
    with SessionLocal() as db:
        return execute_due_automation_rules(db)
