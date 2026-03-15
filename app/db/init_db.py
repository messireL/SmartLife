from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import models  # noqa: F401
from app.db.session import Base, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "postgresql":
        _apply_postgres_migrations()


def _apply_postgres_migrations() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        inspector = inspect(connection)

        def has_table(table_name: str) -> bool:
            return inspector.has_table(table_name)

        def refresh_columns(table_name: str) -> set[str]:
            return {column["name"] for column in inspector.get_columns(table_name)} if has_table(table_name) else set()

        def ensure_column(table_name: str, column_name: str, ddl: str) -> None:
            columns = refresh_columns(table_name)
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))

        def ensure_index(index_name: str, ddl: str) -> None:
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} {ddl}"))

        # Existing tables are often older than the current ORM schema. Reconcile them field by field.
        if has_table("devices"):
            device_columns: dict[str, str] = {
                "custom_name": "VARCHAR(255)",
                "product_id": "VARCHAR(128)",
                "product_name": "VARCHAR(255)",
                "icon_url": "VARCHAR(512)",
                "custom_room_name": "VARCHAR(128)",
                "notes": "TEXT",
                "switch_on": "BOOLEAN",
                "current_power_w": "NUMERIC(12,2)",
                "current_voltage_v": "NUMERIC(12,2)",
                "current_a": "NUMERIC(12,3)",
                "energy_total_kwh": "NUMERIC(14,3)",
                "fault_code": "VARCHAR(255)",
                "last_seen_at": "TIMESTAMP",
                "last_status_at": "TIMESTAMP",
                "last_status_payload": "TEXT",
                "is_hidden": "BOOLEAN DEFAULT FALSE",
                "hidden_reason": "VARCHAR(255)",
                "is_deleted": "BOOLEAN DEFAULT FALSE",
                "deleted_reason": "VARCHAR(255)",
                "deleted_at": "TIMESTAMP",
            }
            for name, ddl in device_columns.items():
                ensure_column("devices", name, ddl)
            connection.execute(text("UPDATE devices SET is_hidden = FALSE WHERE is_hidden IS NULL"))
            connection.execute(text("UPDATE devices SET is_deleted = FALSE WHERE is_deleted IS NULL"))
            ensure_index("ix_devices_is_deleted", "ON devices(is_deleted)")

        if has_table("energy_samples"):
            energy_columns: dict[str, str] = {
                "power_w": "NUMERIC(12,2)",
                "voltage_v": "NUMERIC(12,2)",
                "current_a": "NUMERIC(12,3)",
                "source_note": "VARCHAR(255)",
                "updated_at": "TIMESTAMP DEFAULT NOW()",
            }
            for name, ddl in energy_columns.items():
                ensure_column("energy_samples", name, ddl)

        if has_table("device_status_snapshots"):
            snapshot_columns: dict[str, str] = {
                "switch_on": "BOOLEAN",
                "power_w": "NUMERIC(12,2)",
                "voltage_v": "NUMERIC(12,2)",
                "current_a": "NUMERIC(12,3)",
                "energy_total_kwh": "NUMERIC(14,3)",
                "fault_code": "VARCHAR(255)",
                "source_note": "VARCHAR(255)",
                "raw_payload": "TEXT",
            }
            for name, ddl in snapshot_columns.items():
                ensure_column("device_status_snapshots", name, ddl)

        # These tables might have been created manually in earlier releases. Create them if missing.
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS sync_runs ("
            "id SERIAL PRIMARY KEY, "
            "provider VARCHAR(64) NOT NULL, "
            "trigger VARCHAR(32) NOT NULL, "
            "status VARCHAR(32) NOT NULL, "
            "started_at TIMESTAMP NOT NULL, "
            "finished_at TIMESTAMP NULL, "
            "duration_ms INTEGER NULL, "
            "result_summary TEXT NULL, "
            "error_message TEXT NULL, "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        ))
        if has_table("sync_runs"):
            sync_columns: dict[str, str] = {
                "provider": "VARCHAR(64)",
                "trigger": "VARCHAR(32)",
                "status": "VARCHAR(32)",
                "started_at": "TIMESTAMP",
                "finished_at": "TIMESTAMP",
                "duration_ms": "INTEGER",
                "result_summary": "TEXT",
                "error_message": "TEXT",
                "created_at": "TIMESTAMP DEFAULT NOW()",
            }
            for name, ddl in sync_columns.items():
                ensure_column("sync_runs", name, ddl)
            ensure_index("ix_sync_runs_provider", "ON sync_runs(provider)")
            ensure_index("ix_sync_runs_trigger", "ON sync_runs(trigger)")
            ensure_index("ix_sync_runs_status", "ON sync_runs(status)")
            ensure_index("ix_sync_runs_started_at", "ON sync_runs(started_at)")

        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS device_command_logs ("
            "id SERIAL PRIMARY KEY, "
            "device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE, "
            "command_code VARCHAR(128) NOT NULL, "
            "command_value VARCHAR(255) NOT NULL, "
            "status VARCHAR(32) NOT NULL, "
            "provider VARCHAR(64) NOT NULL, "
            "requested_at TIMESTAMP NOT NULL, "
            "finished_at TIMESTAMP NULL, "
            "result_summary TEXT NULL, "
            "error_message TEXT NULL, "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        ))
        if has_table("device_command_logs"):
            command_columns: dict[str, str] = {
                "device_id": "INTEGER",
                "command_code": "VARCHAR(128)",
                "command_value": "VARCHAR(255)",
                "status": "VARCHAR(32)",
                "provider": "VARCHAR(64)",
                "requested_at": "TIMESTAMP",
                "finished_at": "TIMESTAMP",
                "result_summary": "TEXT",
                "error_message": "TEXT",
                "created_at": "TIMESTAMP DEFAULT NOW()",
            }
            for name, ddl in command_columns.items():
                ensure_column("device_command_logs", name, ddl)
            ensure_index("ix_device_command_logs_device_id", "ON device_command_logs(device_id)")
            ensure_index("ix_device_command_logs_command_code", "ON device_command_logs(command_code)")
            ensure_index("ix_device_command_logs_status", "ON device_command_logs(status)")
            ensure_index("ix_device_command_logs_provider", "ON device_command_logs(provider)")
            ensure_index("ix_device_command_logs_requested_at", "ON device_command_logs(requested_at)")
