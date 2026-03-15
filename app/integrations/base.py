from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, Sequence

from app.db.models import ProviderType


@dataclass(slots=True)
class ProviderDevice:
    external_id: str
    provider: ProviderType
    name: str
    model: str | None = None
    product_id: str | None = None
    product_name: str | None = None
    category: str | None = None
    room_name: str | None = None
    location_name: str | None = None
    icon_url: str | None = None
    is_online: bool = False
    last_seen_at: datetime | None = None
    notes: str | None = None


@dataclass(slots=True)
class ProviderEnergySample:
    external_id: str
    period_start: date
    energy_kwh: Decimal
    power_w: Decimal | None = None
    voltage_v: Decimal | None = None
    current_a: Decimal | None = None
    source_note: str | None = None


@dataclass(slots=True)
class ProviderStatusSnapshot:
    external_id: str
    recorded_at: datetime
    switch_on: bool | None = None
    power_w: Decimal | None = None
    voltage_v: Decimal | None = None
    current_a: Decimal | None = None
    energy_total_kwh: Decimal | None = None
    fault_code: str | None = None
    source_note: str | None = None
    raw_payload: str | None = None


class DeviceProvider(Protocol):
    provider_name: ProviderType

    def get_devices(self) -> list[ProviderDevice]: ...

    def get_daily_energy_samples(self) -> list[ProviderEnergySample]: ...

    def get_monthly_energy_samples(self) -> list[ProviderEnergySample]: ...

    def get_status_snapshots(self, devices: Sequence[ProviderDevice]) -> list[ProviderStatusSnapshot]: ...
