from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppSetting, ProviderType


RUNTIME_KEY_PROVIDER = "provider"
RUNTIME_KEY_TUYA_BASE_URL = "tuya.base_url"
RUNTIME_KEY_TUYA_ACCESS_ID = "tuya.access_id"
RUNTIME_KEY_TUYA_ACCESS_SECRET = "tuya.access_secret"
RUNTIME_KEY_TUYA_PROJECT_CODE = "tuya.project_code"


@dataclass(slots=True)
class RuntimeConfig:
    provider: str
    tuya_base_url: str
    tuya_access_id: str
    tuya_access_secret: str
    tuya_project_code: str

    @property
    def tuya_access_id_masked(self) -> str:
        value = (self.tuya_access_id or "").strip()
        if not value:
            return "не задан"
        if len(value) <= 6:
            return "*" * len(value)
        return f"{value[:3]}***{value[-3:]}"

    @property
    def tuya_access_secret_masked(self) -> str:
        value = (self.tuya_access_secret or "").strip()
        if not value:
            return "не задан"
        return "•" * 8

    @property
    def tuya_is_configured(self) -> bool:
        return bool((self.tuya_access_id or "").strip() and (self.tuya_access_secret or "").strip())


def _get_setting_row(db: Session, key: str) -> AppSetting | None:
    return db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()


def get_setting_value(db: Session, key: str, default: str = "") -> str:
    row = _get_setting_row(db, key)
    if row is None or row.value is None:
        return default
    return str(row.value)


def set_setting_value(db: Session, key: str, value: str | None) -> None:
    row = _get_setting_row(db, key)
    if row is None:
        row = AppSetting(key=key)
        db.add(row)
    row.value = value


def set_runtime_values(db: Session, values: dict[str, str | None]) -> None:
    for key, value in values.items():
        set_setting_value(db, key, value)
    db.commit()


def _build_runtime_config(db: Session) -> RuntimeConfig:
    settings = get_settings()
    return RuntimeConfig(
        provider=get_setting_value(db, RUNTIME_KEY_PROVIDER, settings.smartlife_provider or ProviderType.DEMO.value),
        tuya_base_url=get_setting_value(db, RUNTIME_KEY_TUYA_BASE_URL, settings.smartlife_tuya_base_url or "https://openapi.tuyaeu.com"),
        tuya_access_id=get_setting_value(db, RUNTIME_KEY_TUYA_ACCESS_ID, settings.smartlife_tuya_access_id or ""),
        tuya_access_secret=get_setting_value(db, RUNTIME_KEY_TUYA_ACCESS_SECRET, settings.smartlife_tuya_access_secret or ""),
        tuya_project_code=get_setting_value(db, RUNTIME_KEY_TUYA_PROJECT_CODE, settings.smartlife_tuya_project_code or ""),
    )


def bootstrap_runtime_settings(db: Session) -> RuntimeConfig:
    settings = get_settings()
    defaults = {
        RUNTIME_KEY_PROVIDER: settings.smartlife_provider or ProviderType.DEMO.value,
        RUNTIME_KEY_TUYA_BASE_URL: settings.smartlife_tuya_base_url or "https://openapi.tuyaeu.com",
        RUNTIME_KEY_TUYA_ACCESS_ID: settings.smartlife_tuya_access_id or "",
        RUNTIME_KEY_TUYA_ACCESS_SECRET: settings.smartlife_tuya_access_secret or "",
        RUNTIME_KEY_TUYA_PROJECT_CODE: settings.smartlife_tuya_project_code or "",
    }
    changed = False
    for key, default_value in defaults.items():
        row = _get_setting_row(db, key)
        if row is None:
            db.add(AppSetting(key=key, value=default_value))
            changed = True
    if changed:
        db.commit()
    return _build_runtime_config(db)


def get_runtime_config(db: Session) -> RuntimeConfig:
    bootstrap_runtime_settings(db)
    return _build_runtime_config(db)


def get_runtime_provider_name(db: Session) -> str:
    return get_runtime_config(db).provider


def configure_tuya_cloud(db: Session, *, base_url: str, access_id: str, access_secret: str, project_code: str = "") -> RuntimeConfig:
    set_runtime_values(
        db,
        {
            RUNTIME_KEY_PROVIDER: ProviderType.TUYA_CLOUD.value,
            RUNTIME_KEY_TUYA_BASE_URL: base_url.strip(),
            RUNTIME_KEY_TUYA_ACCESS_ID: access_id.strip(),
            RUNTIME_KEY_TUYA_ACCESS_SECRET: access_secret.strip(),
            RUNTIME_KEY_TUYA_PROJECT_CODE: project_code.strip(),
        },
    )
    return get_runtime_config(db)


def configure_demo_provider(db: Session) -> RuntimeConfig:
    set_runtime_values(db, {RUNTIME_KEY_PROVIDER: ProviderType.DEMO.value})
    return get_runtime_config(db)
