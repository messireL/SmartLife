from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.version import APP_VERSION


_SECRET_DIRS = (
    Path("/run/secrets"),
    Path("/app/secrets"),
    Path("secrets"),
)



def _read_secret(secret_name: str, default: str = "") -> str:
    for secret_dir in _SECRET_DIRS:
        candidate = secret_dir / secret_name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return default


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="SmartLife", validation_alias="SMARTLIFE_APP_NAME")
    app_version: str = Field(default=APP_VERSION)
    app_host: str = Field(default="0.0.0.0", validation_alias="SMARTLIFE_APP_HOST")
    app_port: int = Field(default=18089, validation_alias="SMARTLIFE_APP_PORT")
    app_base_url: str = Field(default="http://192.168.1.100:13443", validation_alias="SMARTLIFE_APP_BASE_URL")
    network_mode: str = Field(default="lan", validation_alias="SMARTLIFE_NETWORK_MODE")
    lan_only: bool = Field(default=True, validation_alias="SMARTLIFE_LAN_ONLY")
    bind_ip: str = Field(default="192.168.1.100", validation_alias="SMARTLIFE_BIND_IP")
    public_port: int = Field(default=13443, validation_alias="SMARTLIFE_PUBLIC_PORT")
    smartlife_provider: str = Field(default="demo", validation_alias="SMARTLIFE_PROVIDER")
    smartlife_tuya_base_url: str = Field(default="https://openapi.tuyaeu.com", validation_alias="SMARTLIFE_TUYA_BASE_URL")
    smartlife_sync_interval_seconds: int = Field(default=60, validation_alias="SMARTLIFE_SYNC_INTERVAL_SECONDS")
    smartlife_background_sync_enabled: bool = Field(default=True, validation_alias="SMARTLIFE_BACKGROUND_SYNC_ENABLED")
    smartlife_sync_on_startup: bool = Field(default=True, validation_alias="SMARTLIFE_SYNC_ON_STARTUP")
    smartlife_xiaomi_region: str = Field(default="cn", validation_alias="SMARTLIFE_XIAOMI_REGION")
    smartlife_xiaomi_device_ip: str = Field(default="", validation_alias="SMARTLIFE_XIAOMI_DEVICE_IP")
    timezone: str = Field(default="Europe/Moscow", validation_alias="SMARTLIFE_TIMEZONE")

    smartlife_db_name: str = Field(default="smartlife", validation_alias="SMARTLIFE_DB_NAME")
    smartlife_db_user: str = Field(default="smartlife", validation_alias="SMARTLIFE_DB_USER")
    smartlife_db_host: str = Field(default="db", validation_alias="SMARTLIFE_DB_HOST")
    smartlife_db_port: int = Field(default=5432, validation_alias="SMARTLIFE_DB_PORT")

    @property
    def app_secret_key(self) -> str:
        return _read_secret("app_secret_key", "change-me")

    @property
    def smartlife_tuya_access_id(self) -> str:
        return _read_secret("smartlife_tuya_access_id")

    @property
    def smartlife_tuya_access_secret(self) -> str:
        return _read_secret("smartlife_tuya_access_secret")

    @property
    def smartlife_tuya_project_code(self) -> str:
        return _read_secret("smartlife_tuya_project_code")

    @property
    def smartlife_xiaomi_username(self) -> str:
        return _read_secret("smartlife_xiaomi_username")

    @property
    def smartlife_xiaomi_password(self) -> str:
        return _read_secret("smartlife_xiaomi_password")

    @property
    def smartlife_xiaomi_device_token(self) -> str:
        return _read_secret("smartlife_xiaomi_device_token")

    @property
    def database_password(self) -> str:
        return _read_secret("db_password", "smartlife")

    @property
    def database_url(self) -> str:
        quoted_user = quote_plus(self.smartlife_db_user)
        quoted_password = quote_plus(self.database_password)
        return (
            f"postgresql+psycopg://{quoted_user}:{quoted_password}@"
            f"{self.smartlife_db_host}:{self.smartlife_db_port}/{self.smartlife_db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
