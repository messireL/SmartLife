from app.core.config import get_settings
from app.integrations.demo_provider import DemoProvider
from app.integrations.tuya_provider import TuyaCloudProvider
from app.integrations.xiaomi_provider import XiaomiMiioProvider


def get_provider():
    settings = get_settings()
    provider_name = settings.smartlife_provider.lower().strip()
    if provider_name == "demo":
        return DemoProvider()
    if provider_name == "tuya_cloud":
        return TuyaCloudProvider()
    if provider_name == "xiaomi_miio":
        return XiaomiMiioProvider()
    raise ValueError(f"Unsupported SMARTLIFE_PROVIDER: {provider_name}")
