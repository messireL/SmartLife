from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SmartLife"
    app_version: str = "0.1.0"
    app_host: str = "0.0.0.0"
    app_port: int = 18089
    app_secret_key: str = "change-me"
    app_base_url: str = "http://localhost:18089"
    database_url: str = "postgresql+psycopg://smartlife:smartlife@db:5432/smartlife"
    smartlife_provider: str = "demo"
    smartlife_tuya_base_url: str = "https://openapi.tuyaeu.com"
    smartlife_tuya_access_id: str = ""
    smartlife_tuya_access_secret: str = ""
    smartlife_tuya_project_code: str = ""
    smartlife_xiaomi_region: str = "cn"
    smartlife_xiaomi_username: str = ""
    smartlife_xiaomi_password: str = ""
    smartlife_xiaomi_device_token: str = ""
    smartlife_xiaomi_device_ip: str = ""
    timezone: str = "Europe/Helsinki"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
