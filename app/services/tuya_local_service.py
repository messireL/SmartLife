from __future__ import annotations

from typing import Any

from app.services.device_lan_service import DeviceLanConfig


class TuyaLocalError(RuntimeError):
    pass


def can_handle_locally(command_code: str | None) -> bool:
    return _switch_dps_index(command_code) is not None


def send_local_command(*, device_id: str, config: DeviceLanConfig, command_code: str, command_value: Any) -> dict[str, Any]:
    dps_index = _switch_dps_index(command_code)
    if dps_index is None:
        raise TuyaLocalError(
            f"Локальный режим SmartLife v0.11.17 пока умеет только switch-команды. {command_code!r} ещё не поддержан."
        )
    if not config.can_switch_locally:
        raise TuyaLocalError("LAN-конфигурация устройства неполная: нужен IP, protocol version и local key.")

    try:
        import tinytuya
    except Exception as exc:  # noqa: BLE001
        raise TuyaLocalError(
            "Библиотека tinytuya не установлена в контейнере приложения. После обновления релиза пересобери app через ./scripts/manage.sh up --build."
        ) from exc

    try:
        version_float = float(config.protocol_version)
    except (TypeError, ValueError) as exc:
        raise TuyaLocalError(f"Некорректная версия протокола: {config.protocol_version!r}") from exc

    try:
        device = tinytuya.Device(device_id, config.local_ip, config.local_key, version=version_float)
        if hasattr(device, "set_version"):
            device.set_version(version_float)
        if hasattr(device, "set_socketPersistent"):
            device.set_socketPersistent(False)
        if hasattr(device, "set_socketTimeout"):
            device.set_socketTimeout(5)
        result = device.set_status(bool(command_value), switch=dps_index)
    except Exception as exc:  # noqa: BLE001
        raise TuyaLocalError(f"Локальная команда не выполнена: {exc}") from exc

    if _looks_like_tinytuya_error(result):
        raise TuyaLocalError(_format_tinytuya_error(result))

    return {
        "transport": "tuya_local",
        "command_code": command_code,
        "dps": dps_index,
        "result": result,
        "ip": config.local_ip,
        "version": config.protocol_version,
    }


def _switch_dps_index(command_code: str | None) -> int | None:
    import re

    code = (command_code or "").strip().lower()
    if code in {"switch", "switch_1"}:
        return 1
    match = re.fullmatch(r"switch_(\d+)", code)
    if match:
        return int(match.group(1))
    return None


def _looks_like_tinytuya_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return "Err" in payload or "Error" in payload


def _format_tinytuya_error(payload: dict[str, Any]) -> str:
    error = str(payload.get("Error") or "Unknown TinyTuya error").strip()
    err_code = str(payload.get("Err") or "").strip()
    if err_code:
        return f"TinyTuya error {err_code}: {error}"
    return error
