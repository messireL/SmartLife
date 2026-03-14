from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.db.models import ProviderType
from app.integrations.base import DeviceProvider, ProviderDevice, ProviderEnergySample


def _month_start_with_offset(base: date, months_back: int) -> date:
    year = base.year
    month = base.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


class DemoProvider(DeviceProvider):
    provider_name = ProviderType.DEMO

    def __init__(self) -> None:
        now = datetime.utcnow().replace(microsecond=0)
        self._devices = [
            ProviderDevice(
                external_id="plug-kitchen-01",
                provider=self.provider_name,
                name="Kitchen Plug",
                model="P110",
                category="smart_plug",
                room_name="Kitchen",
                location_name="Home",
                is_online=True,
                last_seen_at=now,
                notes="Demo Smart Life plug",
            ),
            ProviderDevice(
                external_id="heater-bedroom-01",
                provider=self.provider_name,
                name="Bedroom Heater",
                model="DemoHeater-X",
                category="heater",
                room_name="Bedroom",
                location_name="Home",
                is_online=True,
                last_seen_at=now - timedelta(minutes=3),
                notes="Demo heater with energy history",
            ),
            ProviderDevice(
                external_id="purifier-living-01",
                provider=self.provider_name,
                name="Living Room Purifier",
                model="Mi Air Purifier Demo",
                category="air_purifier",
                room_name="Living room",
                location_name="Home",
                is_online=False,
                last_seen_at=now - timedelta(hours=5),
                notes="Demo Xiaomi-style device",
            ),
        ]

    def get_devices(self) -> list[ProviderDevice]:
        return self._devices

    def get_daily_energy_samples(self) -> list[ProviderEnergySample]:
        today = date.today()
        samples: list[ProviderEnergySample] = []
        for days_ago in range(0, 30):
            day = today - timedelta(days=days_ago)
            samples.extend(
                [
                    ProviderEnergySample(
                        external_id="plug-kitchen-01",
                        period_start=day,
                        energy_kwh=Decimal(f"{0.35 + (days_ago % 5) * 0.04:.3f}"),
                        power_w=Decimal(f"{70 + (days_ago % 4) * 8:.2f}"),
                        voltage_v=Decimal("229.40"),
                        current_a=Decimal("0.31"),
                        source_note="demo daily",
                    ),
                    ProviderEnergySample(
                        external_id="heater-bedroom-01",
                        period_start=day,
                        energy_kwh=Decimal(f"{1.80 + (days_ago % 6) * 0.15:.3f}"),
                        power_w=Decimal(f"{850 + (days_ago % 7) * 20:.2f}"),
                        voltage_v=Decimal("228.90"),
                        current_a=Decimal("3.71"),
                        source_note="demo daily",
                    ),
                    ProviderEnergySample(
                        external_id="purifier-living-01",
                        period_start=day,
                        energy_kwh=Decimal(f"{0.22 + (days_ago % 4) * 0.03:.3f}"),
                        power_w=Decimal(f"{28 + (days_ago % 5) * 3:.2f}"),
                        voltage_v=Decimal("230.10"),
                        current_a=Decimal("0.13"),
                        source_note="demo daily",
                    ),
                ]
            )
        return samples

    def get_monthly_energy_samples(self) -> list[ProviderEnergySample]:
        current_month = date.today().replace(day=1)
        samples: list[ProviderEnergySample] = []
        for months_ago in range(0, 12):
            month = _month_start_with_offset(current_month, months_ago)
            samples.extend(
                [
                    ProviderEnergySample(
                        external_id="plug-kitchen-01",
                        period_start=month,
                        energy_kwh=Decimal(f"{9.40 + (months_ago % 3) * 0.80:.3f}"),
                        source_note="demo monthly",
                    ),
                    ProviderEnergySample(
                        external_id="heater-bedroom-01",
                        period_start=month,
                        energy_kwh=Decimal(f"{44.80 + (months_ago % 4) * 2.70:.3f}"),
                        source_note="demo monthly",
                    ),
                    ProviderEnergySample(
                        external_id="purifier-living-01",
                        period_start=month,
                        energy_kwh=Decimal(f"{6.20 + (months_ago % 5) * 0.55:.3f}"),
                        source_note="demo monthly",
                    ),
                ]
            )
        return samples
