from __future__ import annotations

from app.db.models import ProviderType
from app.integrations.base import DeviceProvider


class XiaomiMiioProvider(DeviceProvider):
    provider_name = ProviderType.XIAOMI_MIIO

    def get_devices(self):
        raise NotImplementedError(
            "Xiaomi miIO / Mi Home integration scaffold is ready, but real device auth/token sync is not wired in this release yet."
        )

    def get_daily_energy_samples(self):
        raise NotImplementedError("Xiaomi daily energy sync is not wired yet.")

    def get_monthly_energy_samples(self):
        raise NotImplementedError("Xiaomi monthly energy sync is not wired yet.")

    def get_status_snapshots(self, devices):
        raise NotImplementedError("Xiaomi live status sync is not wired yet.")

    def send_switch_command(self, device_id: str, switch_on: bool) -> dict:
        raise NotImplementedError("Xiaomi device control is not wired yet.")
