from __future__ import annotations

from sqlalchemy import text

from app.db import models  # noqa: F401
from app.db.session import Base, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "postgresql":
        _apply_postgres_migrations()



def _apply_postgres_migrations() -> None:
    statements = [
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS custom_name VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS product_id VARCHAR(128)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS product_name VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS icon_url VARCHAR(512)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS custom_room_name VARCHAR(128)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS switch_on BOOLEAN",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_power_w NUMERIC(12,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_voltage_v NUMERIC(12,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_a NUMERIC(12,3)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS energy_total_kwh NUMERIC(14,3)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS fault_code VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_status_at TIMESTAMP",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_status_payload TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN DEFAULT FALSE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS hidden_reason VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS deleted_reason VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS ix_devices_is_deleted ON devices(is_deleted)",
        "ALTER TABLE energy_samples ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
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
        ")",
        "CREATE INDEX IF NOT EXISTS ix_sync_runs_provider ON sync_runs(provider)",
        "CREATE INDEX IF NOT EXISTS ix_sync_runs_trigger ON sync_runs(trigger)",
        "CREATE INDEX IF NOT EXISTS ix_sync_runs_status ON sync_runs(status)",
        "CREATE INDEX IF NOT EXISTS ix_sync_runs_started_at ON sync_runs(started_at)",
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
        ")",
        "CREATE INDEX IF NOT EXISTS ix_device_command_logs_device_id ON device_command_logs(device_id)",
        "CREATE INDEX IF NOT EXISTS ix_device_command_logs_command_code ON device_command_logs(command_code)",
        "CREATE INDEX IF NOT EXISTS ix_device_command_logs_status ON device_command_logs(status)",
        "CREATE INDEX IF NOT EXISTS ix_device_command_logs_provider ON device_command_logs(provider)",
        "CREATE INDEX IF NOT EXISTS ix_device_command_logs_requested_at ON device_command_logs(requested_at)",
        "CREATE TABLE IF NOT EXISTS app_settings ("
        "id SERIAL PRIMARY KEY, "
        "key VARCHAR(128) NOT NULL UNIQUE, "
        "value TEXT NULL, "
        "created_at TIMESTAMP DEFAULT NOW(), "
        "updated_at TIMESTAMP DEFAULT NOW()"
        ")",
        "CREATE INDEX IF NOT EXISTS ix_app_settings_key ON app_settings(key)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
