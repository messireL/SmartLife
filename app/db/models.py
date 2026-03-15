from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
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


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[ProviderType] = mapped_column(Enum(ProviderType, name="provider_type"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    room_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    switch_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    current_power_w: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_voltage_v: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_a: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    energy_total_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    fault_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_devices_provider_external_id"),)


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
    source_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="status_snapshots")
