from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import utc_now_naive
from app.db.models import Device, DeviceCommandLog, DeviceCommandStatus, ProviderType, SyncRunTrigger
from app.integrations.registry import get_provider
from app.services.runtime_config_service import get_runtime_config
from app.services.tuya_quota_service import detect_tuya_quota_state, is_tuya_quota_error_message


class DeviceControlError(RuntimeError):
    pass


def _friendly_tuya_quota_control_message(raw_message: str | None = None) -> str:
    base = (
        "Квота Tuya Trial Edition исчерпана. Продли Extended Trial или подключи официальный ресурс-пак, "
        "затем запусти синхронизацию SmartLife, чтобы снять блокировку управления."
    )
    raw = (raw_message or "").strip()
    if raw and raw not in base:
        return f"{base} Tuya says: {raw}"
    return base


def _log_device_command_error(
    db: Session,
    *,
    device: Device,
    command_code: str,
    command_value: Any,
    requested_at,
    trigger: str,
    error_message: str,
) -> None:
    db.add(
        DeviceCommandLog(
            device_id=device.id,
            command_code=command_code,
            command_value=str(command_value),
            status=DeviceCommandStatus.ERROR,
            provider=device.provider.value,
            requested_at=requested_at,
            finished_at=utc_now_naive(),
            error_message=error_message,
            result_summary=f'trigger={trigger}',
        )
    )
    db.commit()



def get_recent_command_logs(db: Session, device_id: int, limit: int = 10) -> list[DeviceCommandLog]:
    limit = max(1, min(limit, 50))
    return db.execute(
        select(DeviceCommandLog)
        .where(DeviceCommandLog.device_id == device_id)
        .order_by(DeviceCommandLog.requested_at.desc(), DeviceCommandLog.id.desc())
        .limit(limit)
    ).scalars().all()



def set_device_switch_state(db: Session, device_id: int, desired_state: bool, *, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = _get_active_device(db, device_id)
    switch_code = _resolve_switch_code(device)
    if switch_code is None:
        raise DeviceControlError('устройство не поддерживает cloud-команду включения/выключения')
    return set_device_switch_code_state(db, device_id, switch_code, desired_state, trigger=trigger)


def set_device_switch_code_state(db: Session, device_id: int, command_code: str, desired_state: bool, *, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = _get_active_device(db, device_id)
    provider = _get_matching_provider(db, device)
    command_code = (command_code or "").strip()
    if not command_code:
        raise DeviceControlError('код канала не должен быть пустым')
    if command_code not in set(device.control_codes):
        raise DeviceControlError(f'устройство не поддерживает канал {command_code}')
    if not _is_switch_like_code(command_code):
        raise DeviceControlError(f'команда {command_code} не является выключателем')
    success_updates = {
        'last_status_at': utc_now_naive(),
    }
    if command_code in {'switch', 'switch_1'}:
        success_updates['switch_on'] = desired_state
    result = _execute_device_command(
        db,
        device=device,
        provider=provider,
        command_code=command_code,
        command_value=bool(desired_state),
        trigger=trigger,
        success_updates=success_updates,
    )
    result['switch_on'] = desired_state
    result['command_code'] = command_code
    return result


def set_device_multiple_switch_codes_state(db: Session, device_id: int, command_codes: list[str] | tuple[str, ...], desired_state: bool, *, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    codes: list[str] = []
    seen: set[str] = set()
    for raw_code in command_codes:
        code = (raw_code or '').strip()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    if not codes:
        raise DeviceControlError('не переданы каналы для групповой команды')

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for code in codes:
        try:
            results.append(set_device_switch_code_state(db, device_id, code, desired_state, trigger=trigger))
        except DeviceControlError as exc:
            errors.append(f'{code}: {exc}')

    if not results:
        raise DeviceControlError('; '.join(errors) if errors else 'групповая команда не выполнена')

    return {
        'device_id': device_id,
        'desired_state': desired_state,
        'command_codes': [item['command_code'] for item in results],
        'success_count': len(results),
        'error_count': len(errors),
        'errors': errors,
    }



def set_device_boolean_code_state(db: Session, device_id: int, command_code: str, desired_state: bool, *, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = _get_active_device(db, device_id)
    provider = _get_matching_provider(db, device)
    code = (command_code or '').strip()
    if not code:
        raise DeviceControlError('код команды не должен быть пустым')
    if code not in set(device.control_codes):
        raise DeviceControlError(f'устройство не поддерживает команду {code}')
    result = _execute_device_command(
        db,
        device=device,
        provider=provider,
        command_code=code,
        command_value=bool(desired_state),
        trigger=trigger,
        success_updates={
            'last_status_at': utc_now_naive(),
        },
    )
    result['command_code'] = code
    result['value'] = bool(desired_state)
    return result



def set_device_enum_code_value(db: Session, device_id: int, command_code: str, desired_value: str, *, allowed_values: list[str] | tuple[str, ...] | None = None, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = _get_active_device(db, device_id)
    provider = _get_matching_provider(db, device)
    code = (command_code or '').strip()
    value = (desired_value or '').strip()
    if not code:
        raise DeviceControlError('код команды не должен быть пустым')
    if not value:
        raise DeviceControlError('значение не должно быть пустым')
    if code not in set(device.control_codes):
        raise DeviceControlError(f'устройство не поддерживает команду {code}')
    allowed = [str(item).strip() for item in (allowed_values or []) if str(item).strip()]
    if allowed and value not in allowed:
        raise DeviceControlError(f'значение {value!r} не входит в допустимый список')
    result = _execute_device_command(
        db,
        device=device,
        provider=provider,
        command_code=code,
        command_value=value,
        trigger=trigger,
        success_updates={
            'last_status_at': utc_now_naive(),
        },
    )
    result['command_code'] = code
    result['value'] = value
    return result



def set_device_integer_code_value(db: Session, device_id: int, command_code: str, desired_value: str, *, minimum: int | None = None, maximum: int | None = None, step: int | None = None, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = _get_active_device(db, device_id)
    provider = _get_matching_provider(db, device)
    code = (command_code or '').strip()
    raw = (desired_value or '').strip()
    if not code:
        raise DeviceControlError('код команды не должен быть пустым')
    if not raw:
        raise DeviceControlError('значение не должно быть пустым')
    if code not in set(device.control_codes):
        raise DeviceControlError(f'устройство не поддерживает команду {code}')
    try:
        value = int(raw)
    except ValueError as exc:
        raise DeviceControlError('значение должно быть целым числом') from exc
    if minimum is not None and value < minimum:
        raise DeviceControlError(f'значение ниже допустимого минимума {minimum}')
    if maximum is not None and value > maximum:
        raise DeviceControlError(f'значение выше допустимого максимума {maximum}')
    if step and step > 0:
        base = minimum or 0
        if (value - base) % step != 0:
            raise DeviceControlError(f'значение должно идти с шагом {step}')
    result = _execute_device_command(
        db,
        device=device,
        provider=provider,
        command_code=code,
        command_value=value,
        trigger=trigger,
        success_updates={
            'last_status_at': utc_now_naive(),
        },
    )
    result['command_code'] = code
    result['value'] = value
    return result



def set_device_mode(db: Session, device_id: int, desired_mode: str, *, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = _get_active_device(db, device_id)
    provider = _get_matching_provider(db, device)
    mode = (desired_mode or '').strip()
    if not mode:
        raise DeviceControlError('режим не должен быть пустым')
    available_modes = device.available_modes
    if available_modes and mode not in available_modes:
        raise DeviceControlError(f'режим {mode!r} не поддерживается устройством')
    result = _execute_device_command(
        db,
        device=device,
        provider=provider,
        command_code='mode',
        command_value=mode,
        trigger=trigger,
        success_updates={
            'operation_mode': mode,
            'last_status_at': utc_now_naive(),
        },
    )
    result['operation_mode'] = mode
    return result



def set_device_target_temperature(db: Session, device_id: int, desired_value: str, *, trigger: str = SyncRunTrigger.MANUAL.value) -> dict[str, Any]:
    device = _get_active_device(db, device_id)
    provider = _get_matching_provider(db, device)
    raw = (desired_value or '').strip().replace(',', '.')
    if not raw:
        raise DeviceControlError('температура не должна быть пустой')
    try:
        desired_decimal = Decimal(raw)
    except InvalidOperation as exc:
        raise DeviceControlError('температура должна быть числом') from exc

    if device.target_temperature_min_c is not None and desired_decimal < Decimal(device.target_temperature_min_c):
        raise DeviceControlError(f'температура ниже допустимого минимума {device.target_temperature_min_c}')
    if device.target_temperature_max_c is not None and desired_decimal > Decimal(device.target_temperature_max_c):
        raise DeviceControlError(f'температура выше допустимого максимума {device.target_temperature_max_c}')

    step = Decimal(device.target_temperature_step_c) if device.target_temperature_step_c is not None else None
    minimum = Decimal(device.target_temperature_min_c) if device.target_temperature_min_c is not None else None
    if step and step > 0:
        base = minimum if minimum is not None else Decimal('0')
        remainder = (desired_decimal - base) % step
        if remainder != 0:
            raise DeviceControlError(f'температура должна идти с шагом {step}')

    int_value = int(desired_decimal)
    if desired_decimal != Decimal(int_value):
        raise DeviceControlError('сейчас поддерживаются только целые значения температуры')

    result = _execute_device_command(
        db,
        device=device,
        provider=provider,
        command_code='temp_set',
        command_value=int_value,
        trigger=trigger,
        success_updates={
            'target_temperature_c': desired_decimal.quantize(Decimal('0.01')),
            'last_status_at': utc_now_naive(),
        },
    )
    result['target_temperature_c'] = float(desired_decimal)
    return result



def _get_active_device(db: Session, device_id: int) -> Device:
    device = db.get(Device, device_id)
    if device is None or device.is_deleted:
        raise DeviceControlError('device not found')
    return device



def _get_matching_provider(db: Session, device: Device):
    provider = get_provider(db)
    if getattr(provider, 'provider_name', None) != device.provider:
        raise DeviceControlError('active provider does not match selected device provider')
    if not hasattr(provider, 'send_device_command'):
        raise DeviceControlError(f'provider {device.provider.value} does not support device commands yet')
    return provider



def _resolve_switch_code(device: Device) -> str | None:
    codes = set(device.control_codes)
    for code in ('switch', 'switch_1'):
        if code in codes:
            return code
    switch_like = sorted((code for code in codes if _is_switch_like_code(code)), key=_switch_code_sort_key)
    return switch_like[0] if switch_like else None


def _is_switch_like_code(code: str | None) -> bool:
    import re
    if not code:
        return False
    return bool(code == "switch" or re.fullmatch(r"switch_[1-9]\d*", code) or re.fullmatch(r"switch_usb[1-9]\d*", code) or code == "switch_usb")


def _switch_code_sort_key(code: str) -> tuple[int, int, str]:
    import re
    if code == "switch":
        return (0, 0, code)
    match = re.fullmatch(r"switch_(\d+)", code or "")
    if match:
        return (1, int(match.group(1)), code)
    if code == "switch_usb":
        return (2, 0, code)
    match = re.fullmatch(r"switch_usb(\d+)", code or "")
    if match:
        return (2, int(match.group(1)), code)
    return (9, 0, code or "")



def _execute_device_command(
    db: Session,
    *,
    device: Device,
    provider,
    command_code: str,
    command_value: Any,
    trigger: str,
    success_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if command_code not in set(device.control_codes):
        raise DeviceControlError(f'устройство не поддерживает команду {command_code}')

    requested_at = utc_now_naive()
    runtime = get_runtime_config(db)
    if device.provider == ProviderType.TUYA_CLOUD:
        quota_state = detect_tuya_quota_state(db, runtime=runtime)
        if quota_state.exhausted:
            message = _friendly_tuya_quota_control_message(quota_state.message)
            _log_device_command_error(
                db,
                device=device,
                command_code=command_code,
                command_value=command_value,
                requested_at=requested_at,
                trigger=trigger,
                error_message=message,
            )
            raise DeviceControlError(message)

    try:
        result = provider.send_device_command(device.external_id, command_code, command_value)
        for field_name, value in (success_updates or {}).items():
            setattr(device, field_name, value)
        db.add(
            DeviceCommandLog(
                device_id=device.id,
                command_code=command_code,
                command_value=str(command_value),
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
            'provider': device.provider.value,
            'command_code': command_code,
            'result': result,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        message = str(exc)
        if device.provider == ProviderType.TUYA_CLOUD and is_tuya_quota_error_message(message):
            message = _friendly_tuya_quota_control_message(message)
        _log_device_command_error(
            db,
            device=device,
            command_code=command_code,
            command_value=command_value,
            requested_at=requested_at,
            trigger=trigger,
            error_message=message,
        )
        raise DeviceControlError(message) from exc
