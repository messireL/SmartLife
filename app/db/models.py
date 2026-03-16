from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ProviderType(StrEnum):
    DEMO = "demo"
    TUYA_CLOUD = "tuya_cloud"
    XIAOMI_MIIO = "xiaomi_miio"


class BucketType(StrEnum):
    DAY = "day"
    MONTH = "month"


class SyncRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


class SyncRunTrigger(StrEnum):
    MANUAL = "manual"
    BACKGROUND = "background"
    STARTUP = "startup"
    CLI = "cli"


class DeviceCommandStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


class DeviceBadge(Base):
    __tablename__ = "device_badges"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    color: Mapped[str] = mapped_column(String(32), default="slate")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())

    devices: Mapped[list["Device"]] = relationship(back_populates="badge")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[ProviderType] = mapped_column(Enum(ProviderType, name="provider_type"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    custom_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    room_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    custom_room_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    badge_id: Mapped[int | None] = mapped_column(ForeignKey("device_badges.id", ondelete="SET NULL"), nullable=True, index=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    switch_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    current_power_w: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_voltage_v: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_a: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    energy_total_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    fault_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    target_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    operation_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    control_codes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_modes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_temperature_min_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    target_temperature_max_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    target_temperature_step_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_status_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())

    energy_samples: Mapped[list["EnergySample"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", order_by="desc(EnergySample.period_start)"
    )
    status_snapshots: Mapped[list["DeviceStatusSnapshot"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", order_by="desc(DeviceStatusSnapshot.recorded_at)"
    )
    command_logs: Mapped[list["DeviceCommandLog"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", order_by="desc(DeviceCommandLog.requested_at)"
    )
    badge: Mapped[DeviceBadge | None] = relationship(back_populates="devices")

    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_devices_provider_external_id"),)

    @property
    def display_name(self) -> str:
        value = (self.custom_name or "").strip()
        return value or self.name

    @property
    def display_room_name(self) -> str | None:
        value = (self.custom_room_name or "").strip()
        return value or self.room_name

    @property
    def control_codes(self) -> list[str]:
        return _parse_json_list(self.control_codes_json)

    @property
    def available_modes(self) -> list[str]:
        return _parse_json_list(self.available_modes_json)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())


class EnergySample(Base):
    __tablename__ = "energy_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    bucket_type: Mapped[BucketType] = mapped_column(Enum(BucketType, name="bucket_type"), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    energy_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0.000"))
    power_w: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    voltage_v: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_a: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    source_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())

    device: Mapped[Device] = relationship(back_populates="energy_samples")

    __table_args__ = (UniqueConstraint("device_id", "bucket_type", "period_start", name="uq_energy_period"),)


class DeviceStatusSnapshot(Base):
    __tablename__ = "device_status_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    switch_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    power_w: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    voltage_v: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_a: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    energy_total_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    fault_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    target_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    operation_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="status_snapshots")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    trigger: Mapped[SyncRunTrigger] = mapped_column(Enum(SyncRunTrigger, name="sync_run_trigger"), index=True)
    status: Mapped[SyncRunStatus] = mapped_column(Enum(SyncRunStatus, name="sync_run_status"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class DeviceCommandLog(Base):
    __tablename__ = "device_command_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    command_code: Mapped[str] = mapped_column(String(128), index=True)
    command_value: Mapped[str] = mapped_column(String(255))
    status: Mapped[DeviceCommandStatus] = mapped_column(Enum(DeviceCommandStatus, name="device_command_status"), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="command_logs")



def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]
