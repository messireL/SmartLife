from __future__ import annotations

from app.db.models import ProviderType
from app.integrations.base import DeviceProvider


class TuyaCloudProvider(DeviceProvider):
    provider_name = ProviderType.TUYA_CLOUD

    def get_devices(self):
        raise NotImplementedError(
            "Tuya Cloud integration scaffold is ready, but signed API requests and account mapping are not wired in this first release yet."
        )

    def get_daily_energy_samples(self):
        raise NotImplementedError("Tuya daily energy sync is not wired yet.")

    def get_monthly_energy_samples(self):
        raise NotImplementedError("Tuya monthly energy sync is not wired yet.")
