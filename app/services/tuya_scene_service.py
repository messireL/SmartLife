from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.tuya_provider import TuyaApiError, TuyaOpenApiClient
from app.services.runtime_config_service import (
    RUNTIME_KEY_TUYA_BASE_URL,
    RUNTIME_KEY_TUYA_ACCESS_ID,
    RUNTIME_KEY_TUYA_ACCESS_SECRET,
    get_runtime_config,
    get_setting_value,
    set_setting_value,
)

APP_KEY_TUYA_SCENE_HOME_IDS = "tuya.scene_home_ids_csv"


@dataclass(slots=True)
class TuyaSceneChoice:
    value: str
    label: str
    home_id: str
    scene_id: str
    home_name: str
    scene_name: str

    def to_dict(self) -> dict[str, str]:
        return {
            "value": self.value,
            "label": self.label,
            "home_id": self.home_id,
            "scene_id": self.scene_id,
            "home_name": self.home_name,
            "scene_name": self.scene_name,
            "kind": "scene",
        }


class TuyaSceneBridgeError(RuntimeError):
    pass


def get_configured_home_ids(db: Session) -> list[str]:
    raw = get_setting_value(db, APP_KEY_TUYA_SCENE_HOME_IDS, "")
    items = []
    for chunk in str(raw or "").replace("\n", ",").split(","):
        value = chunk.strip()
        if value and value not in items:
            items.append(value)
    return items


def save_configured_home_ids(db: Session, raw_value: str) -> list[str]:
    normalized = ",".join(get_normalized_home_ids(raw_value))
    set_setting_value(db, APP_KEY_TUYA_SCENE_HOME_IDS, normalized)
    db.commit()
    return get_configured_home_ids(db)


def get_normalized_home_ids(raw_value: str) -> list[str]:
    items = []
    for chunk in str(raw_value or "").replace("\n", ",").split(","):
        value = chunk.strip()
        if value and value not in items:
            items.append(value)
    return items


def _get_client(db: Session) -> TuyaOpenApiClient:
    runtime = get_runtime_config(db)
    if runtime.provider != "tuya_cloud":
        raise TuyaSceneBridgeError("Tuya Cloud сейчас не выбран как активный провайдер.")
    access_id = (runtime.tuya_access_id or "").strip()
    access_secret = (runtime.tuya_access_secret or "").strip()
    if not access_id or not access_secret:
        raise TuyaSceneBridgeError("Для моста Tuya-сцен нужны сохранённые Access ID и Access Secret.")
    return TuyaOpenApiClient(
        base_url=(runtime.tuya_base_url or "").strip() or get_setting_value(db, RUNTIME_KEY_TUYA_BASE_URL, "https://openapi.tuyaeu.com"),
        access_id=access_id,
        access_secret=access_secret,
    )


def _extract_rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("list", "result", "records", "data", "scenes", "automations"):
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _scene_name(item: dict[str, Any]) -> str:
    return str(
        item.get("name")
        or item.get("scene_name")
        or item.get("sceneName")
        or item.get("automation_name")
        or item.get("automationName")
        or item.get("id")
        or "Без имени"
    )


def _scene_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("scene_id") or item.get("sceneId") or item.get("automation_id") or item.get("automationId") or "")


def _is_enabled(item: dict[str, Any]) -> bool | None:
    for key in ("enabled", "enable", "is_enabled", "status", "executionState"):
        if key not in item:
            continue
        value = item.get(key)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "enabled", "enable", "open", "on"}:
            return True
        if text in {"0", "false", "disabled", "disable", "close", "off"}:
            return False
    return None


def get_tuya_scene_bridge_overview(db: Session) -> dict[str, Any]:
    home_ids = get_configured_home_ids(db)
    overview: dict[str, Any] = {
        "configured_home_ids": home_ids,
        "configured_home_ids_csv": ", ".join(home_ids),
        "homes": [],
        "scene_choices": [],
        "scene_index": {},
        "warnings": [],
        "errors": [],
        "is_configured": False,
    }
    if not home_ids:
        overview["warnings"].append("Не заданы home_id для Tuya-сцен. Их можно добавить в Настройках.")
        return overview
    try:
        client = _get_client(db)
    except TuyaSceneBridgeError as exc:
        overview["errors"].append(str(exc))
        return overview

    overview["is_configured"] = True
    for home_id in home_ids:
        home_entry = {
            "home_id": home_id,
            "home_name": f"Дом {home_id}",
            "scenes": [],
            "automations": [],
            "error": None,
        }
        try:
            home_info = client.get_home_details(home_id)
            home_entry["home_name"] = str(home_info.get("name") or home_info.get("home_name") or home_id)
            scenes = client.list_home_scenes(home_id)
            automations = client.list_home_automations(home_id)
            home_entry["scenes"] = [
                {
                    "id": _scene_id(item),
                    "name": _scene_name(item),
                    "enabled": _is_enabled(item),
                    "raw": item,
                }
                for item in scenes
                if _scene_id(item)
            ]
            home_entry["automations"] = [
                {
                    "id": _scene_id(item),
                    "name": _scene_name(item),
                    "enabled": _is_enabled(item),
                    "raw": item,
                }
                for item in automations
                if _scene_id(item)
            ]
        except Exception as exc:
            message = f"home_id {home_id}: {exc}"
            home_entry["error"] = message
            overview["errors"].append(message)
        overview["homes"].append(home_entry)

    scene_choices: list[TuyaSceneChoice] = []
    scene_index: dict[str, dict[str, str]] = {}
    for home in overview["homes"]:
        for scene in home["scenes"]:
            scene_choice = TuyaSceneChoice(
                value=f"scene:{home['home_id']}:{scene['id']}",
                label=f"Tuya · {home['home_name']} · {scene['name']}",
                home_id=home["home_id"],
                scene_id=scene["id"],
                home_name=home["home_name"],
                scene_name=scene["name"],
            )
            scene_choices.append(scene_choice)
            scene_index[f"{home['home_id']}:{scene['id']}"] = scene_choice.to_dict()
    overview["scene_choices"] = [item.to_dict() for item in scene_choices]
    overview["scene_index"] = scene_index
    return overview


def get_tuya_scene_choices(db: Session) -> list[dict[str, str]]:
    return get_tuya_scene_bridge_overview(db).get("scene_choices", [])


def trigger_tuya_scene(db: Session, *, home_id: str, scene_id: str) -> dict[str, Any]:
    client = _get_client(db)
    return client.trigger_scene(home_id, scene_id)


def set_tuya_automation_enabled(db: Session, *, home_id: str, automation_id: str, enabled: bool) -> dict[str, Any]:
    client = _get_client(db)
    return client.set_automation_enabled(home_id, automation_id, enabled=enabled)
