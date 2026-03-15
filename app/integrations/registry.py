from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.demo_provider import DemoProvider
from app.integrations.tuya_provider import TuyaCloudProvider
from app.integrations.xiaomi_provider import XiaomiMiioProvider
from app.services.runtime_config_service import get_runtime_provider_name


def get_provider(db: Session | None = None):
    if db is not None:
        provider_name = get_runtime_provider_name(db).lower().strip()
    else:
        with SessionLocal() as session:
            provider_name = get_runtime_provider_name(session).lower().strip()
    if not provider_name:
        provider_name = get_settings().smartlife_provider.lower().strip()
    if provider_name == "demo":
        return DemoProvider()
    if provider_name == "tuya_cloud":
        return TuyaCloudProvider()
    if provider_name == "xiaomi_miio":
        return XiaomiMiioProvider()
    raise ValueError(f"Unsupported SMARTLIFE provider: {provider_name}")
