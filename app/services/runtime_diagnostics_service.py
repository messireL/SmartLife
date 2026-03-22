from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.core.timeutils import get_app_timezone
from app.db.models import AppSetting, ProviderType
from app.services.runtime_config_service import (
    RuntimeConfig,
    TariffPlan,
    get_runtime_config,
    get_tariff_change_target_month,
)
from app.services.tuya_quota_service import detect_tuya_quota_state

REQUIRED_SCHEMA: dict[str, tuple[str, ...]] = {
    "app_settings": ("id", "key", "value", "created_at", "updated_at"),
    "devices": (
        "id",
        "external_id",
        "provider",
        "custom_name",
        "product_id",
        "product_name",
        "custom_room_name",
        "notes",
        "switch_on",
        "current_power_w",
        "current_voltage_v",
        "current_a",
        "energy_total_kwh",
        "fault_code",
        "device_profile",
        "current_temperature_c",
        "target_temperature_c",
        "operation_mode",
        "control_codes_json",
        "available_modes_json",
        "target_temperature_min_c",
        "target_temperature_max_c",
        "target_temperature_step_c",
        "last_seen_at",
        "last_status_at",
        "last_status_payload",
        "is_hidden",
        "hidden_reason",
        "is_deleted",
        "deleted_reason",
        "deleted_at",
    ),
    "device_status_snapshots": (
        "id",
        "device_id",
        "recorded_at",
        "switch_on",
        "power_w",
        "voltage_v",
        "current_a",
        "energy_total_kwh",
        "fault_code",
        "current_temperature_c",
        "target_temperature_c",
        "operation_mode",
        "source_note",
        "raw_payload",
    ),
    "energy_samples": ("id", "device_id", "bucket_type", "period_start", "energy_kwh", "updated_at"),
    "sync_runs": ("id", "provider", "trigger", "status", "started_at", "finished_at"),
    "device_command_logs": (
        "id",
        "device_id",
        "command_code",
        "command_value",
        "status",
        "provider",
        "requested_at",
    ),
}


@dataclass(slots=True)
class RuntimeDiagnostics:
    status: str
    schema_ready: bool
    runtime_ready: bool
    today_local_date: str
    current_month_start: str
    tariff_change_target_month: str
    app_settings_count: int | None
    provider: str
    provider_configured: bool
    tuya_api_mode: str
    tuya_full_sync_interval_minutes: int
    tuya_spec_cache_hours: int
    tuya_last_full_sync_at: str
    backup_keep_last: int
    backup_auto_prune_enabled: bool
    tuya_quota_exhausted: bool
    tuya_quota_detected_at: str | None
    tuya_quota_source: str | None
    tuya_quota_message: str | None
    tariff_mode: str
    tariff_effective_from: str
    tariff_history_count: int
    next_tariff_effective_from: str | None
    missing_tables: list[str]
    missing_columns: dict[str, list[str]]
    schema_issues: list[str]
    warnings: list[str]
    active_plan: dict[str, str] | None
    next_plan: dict[str, str] | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)



def _inspect_schema(db: Session) -> tuple[list[str], dict[str, list[str]], list[str]]:
    inspector = inspect(db.get_bind())
    tables = set(inspector.get_table_names())
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    issues: list[str] = []

    for table_name, required_columns in REQUIRED_SCHEMA.items():
        if table_name not in tables:
            missing_tables.append(table_name)
            issues.append(f"missing table: {table_name}")
            continue
        available_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing = sorted(column for column in required_columns if column not in available_columns)
        if missing:
            missing_columns[table_name] = missing
            issues.append(f"missing columns in {table_name}: {', '.join(missing)}")

    return sorted(missing_tables), missing_columns, issues



def _next_plan_for_month(history: tuple[TariffPlan, ...], current_month_start: date) -> TariffPlan | None:
    for plan in sorted(history, key=lambda item: item.effective_from_date):
        if plan.effective_from_date > current_month_start:
            return plan
    return None



def get_runtime_diagnostics(db: Session) -> RuntimeDiagnostics:
    runtime = get_runtime_config(db)
    missing_tables, missing_columns, schema_issues = _inspect_schema(db)

    quota_state = detect_tuya_quota_state(db, runtime=runtime)
    history = tuple(sorted(runtime.tariff_plan_history, key=lambda item: item.effective_from_date))
    active_plan = next((plan for plan in history if plan.effective_from == runtime.tariff_effective_from), history[-1] if history else None)
    today_local = datetime.now(get_app_timezone()).date()
    current_month_start = today_local.replace(day=1)
    active_month_start = active_plan.effective_from_date if active_plan else date.fromisoformat(runtime.tariff_effective_from)
    next_plan = _next_plan_for_month(history, current_month_start)
    change_target_month = get_tariff_change_target_month(today_local)

    warnings: list[str] = []
    if runtime.provider == ProviderType.TUYA_CLOUD.value and not runtime.tuya_is_configured:
        warnings.append("provider=tuya_cloud, но Access ID / Secret в PostgreSQL не заданы полностью")
    if runtime.provider == ProviderType.TUYA_CLOUD.value and runtime.tuya_api_mode == "economy":
        warnings.append(f"tuya economy mode включён: полный cloud refresh каждые {runtime.tuya_full_sync_interval_minutes} мин, cached spec до {runtime.tuya_spec_cache_hours} ч")
    if runtime.provider == ProviderType.TUYA_CLOUD.value and runtime.tuya_api_mode == "manual":
        warnings.append("tuya manual mode включён: автоматический cloud sync выключен, ключи/IP подтягиваются только ручными запросами по устройству")
    if runtime.backup_auto_prune_enabled and runtime.backup_keep_last > 0:
        warnings.append(f"backup auto-prune включён: храним последние {runtime.backup_keep_last} dump-файлов")
    if quota_state.exhausted:
        warnings.append("Tuya Trial quota exhausted: cloud-команды и часть sync сейчас будут упираться в лимит API")
    if not history:
        warnings.append("история тарифов пуста; будет использован fallback из legacy-значений")
    if runtime.tariff_effective_from != active_month_start.isoformat():
        warnings.append("active runtime tariff does not match selected history month")

    app_settings_count: int | None = None
    if "app_settings" not in missing_tables:
        app_settings_count = int(db.scalar(select(func.count()).select_from(AppSetting)) or 0)

    schema_ready = not schema_issues
    runtime_ready = active_plan is not None and len(history) >= 1
    status = "ok" if schema_ready and runtime_ready else "error"

    return RuntimeDiagnostics(
        status=status,
        schema_ready=schema_ready,
        runtime_ready=runtime_ready,
        today_local_date=today_local.isoformat(),
        current_month_start=current_month_start.isoformat(),
        tariff_change_target_month=change_target_month.isoformat(),
        app_settings_count=app_settings_count,
        provider=runtime.provider,
        provider_configured=runtime.provider != ProviderType.TUYA_CLOUD.value or runtime.tuya_is_configured,
        tuya_api_mode=runtime.tuya_api_mode,
        tuya_full_sync_interval_minutes=runtime.tuya_full_sync_interval_minutes,
        tuya_spec_cache_hours=runtime.tuya_spec_cache_hours,
        tuya_last_full_sync_at=runtime.tuya_last_full_sync_at,
        backup_keep_last=runtime.backup_keep_last,
        backup_auto_prune_enabled=runtime.backup_auto_prune_enabled,
        tuya_quota_exhausted=quota_state.exhausted,
        tuya_quota_detected_at=quota_state.detected_at.isoformat() if quota_state.detected_at else None,
        tuya_quota_source=quota_state.source,
        tuya_quota_message=quota_state.message,
        tariff_mode=runtime.tariff_mode,
        tariff_effective_from=runtime.tariff_effective_from,
        tariff_history_count=len(history),
        next_tariff_effective_from=next_plan.effective_from if next_plan else None,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        schema_issues=schema_issues,
        warnings=warnings,
        active_plan=active_plan.to_dict() if active_plan else None,
        next_plan=next_plan.to_dict() if next_plan else None,
    )



def ensure_runtime_startup_ready(db: Session) -> RuntimeDiagnostics:
    diagnostics = get_runtime_diagnostics(db)
    blocking_issues = list(diagnostics.schema_issues)
    if not diagnostics.runtime_ready:
        blocking_issues.append("runtime diagnostics: active tariff plan could not be resolved")
    if blocking_issues:
        raise RuntimeError("SmartLife startup diagnostics failed: " + "; ".join(blocking_issues))
    return diagnostics
