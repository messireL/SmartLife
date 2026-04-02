from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

ZERO = Decimal("0.000")
MAX_POWER_INTEGRATION_GAP_SECONDS = 6 * 60 * 60


@dataclass(slots=True)
class TelemetryEnergyDelta:
    delta_kwh: Decimal
    source_note: str
    method: str


def estimate_energy_delta(
    *,
    previous_recorded_at: datetime | None,
    previous_energy_total_kwh: Decimal | None,
    previous_power_w: Decimal | None,
    current_recorded_at: datetime | None,
    current_energy_total_kwh: Decimal | None,
    current_power_w: Decimal | None,
) -> TelemetryEnergyDelta | None:
    if previous_recorded_at is None or current_recorded_at is None:
        return None

    delta_from_counter = _counter_delta(previous_energy_total_kwh, current_energy_total_kwh)
    if delta_from_counter is not None and delta_from_counter > ZERO:
        return TelemetryEnergyDelta(
            delta_kwh=delta_from_counter,
            source_note='live energy delta',
            method='energy_total',
        )

    delta_from_power = _power_delta(
        previous_recorded_at=previous_recorded_at,
        previous_power_w=previous_power_w,
        current_recorded_at=current_recorded_at,
        current_power_w=current_power_w,
    )
    if delta_from_power is None or delta_from_power <= ZERO:
        return None

    return TelemetryEnergyDelta(
        delta_kwh=delta_from_power,
        source_note='estimated from power snapshots',
        method='power_integration',
    )


def _counter_delta(previous_total: Decimal | None, current_total: Decimal | None) -> Decimal | None:
    if previous_total is None or current_total is None:
        return None
    return (Decimal(current_total) - Decimal(previous_total)).quantize(Decimal('0.001'))


def _power_delta(
    *,
    previous_recorded_at: datetime,
    previous_power_w: Decimal | None,
    current_recorded_at: datetime,
    current_power_w: Decimal | None,
) -> Decimal | None:
    if previous_power_w is None or current_power_w is None:
        return None
    delta_seconds = int((current_recorded_at - previous_recorded_at).total_seconds())
    if delta_seconds <= 0 or delta_seconds > MAX_POWER_INTEGRATION_GAP_SECONDS:
        return None
    avg_power_w = (Decimal(previous_power_w) + Decimal(current_power_w)) / Decimal('2')
    if avg_power_w <= 0:
        return None
    hours = Decimal(delta_seconds) / Decimal('3600')
    delta_kwh = (avg_power_w * hours / Decimal('1000')).quantize(Decimal('0.001'))
    return delta_kwh if delta_kwh > ZERO else None
