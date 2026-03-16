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
        "CREATE TABLE IF NOT EXISTS device_badges ("
        "id SERIAL PRIMARY KEY, "
        "key VARCHAR(64) NOT NULL UNIQUE, "
        "name VARCHAR(64) NOT NULL, "
        "color VARCHAR(32) NOT NULL DEFAULT 'slate', "
        "created_at TIMESTAMP DEFAULT NOW(), "
        "updated_at TIMESTAMP DEFAULT NOW()"
        ")",
        "CREATE INDEX IF NOT EXISTS ix_device_badges_key ON device_badges(key)",
        "CREATE INDEX IF NOT EXISTS ix_device_badges_name ON device_badges(name)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS custom_name VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS product_id VARCHAR(128)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS product_name VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS icon_url VARCHAR(512)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS custom_room_name VARCHAR(128)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS badge_id INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_devices_badge_id ON devices(badge_id)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS switch_on BOOLEAN",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_power_w NUMERIC(12,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_voltage_v NUMERIC(12,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_a NUMERIC(12,3)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS energy_total_kwh NUMERIC(14,3)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS fault_code VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_profile VARCHAR(64)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_temperature_c NUMERIC(8,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS target_temperature_c NUMERIC(8,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS operation_mode VARCHAR(64)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS control_codes_json TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS available_modes_json TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS channel_aliases_json TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS channel_roles_json TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS channel_icons_json TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS tariff_profile_key VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_devices_tariff_profile_key ON devices(tariff_profile_key)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS target_temperature_min_c NUMERIC(8,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS target_temperature_max_c NUMERIC(8,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS target_temperature_step_c NUMERIC(8,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_status_at TIMESTAMP",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_status_payload TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN DEFAULT FALSE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS hidden_reason VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS deleted_reason VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS ix_devices_is_deleted ON devices(is_deleted)",
        "ALTER TABLE device_status_snapshots ADD COLUMN IF NOT EXISTS current_temperature_c NUMERIC(8,2)",
        "ALTER TABLE device_status_snapshots ADD COLUMN IF NOT EXISTS target_temperature_c NUMERIC(8,2)",
        "ALTER TABLE device_status_snapshots ADD COLUMN IF NOT EXISTS operation_mode VARCHAR(64)",
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
        "CREATE TABLE IF NOT EXISTS automation_rules ("
        "id SERIAL PRIMARY KEY, "
        "name VARCHAR(128) NOT NULL, "
        "device_id INTEGER NULL REFERENCES devices(id) ON DELETE CASCADE, "
        "command_code VARCHAR(128) NOT NULL, "
        "action_kind VARCHAR(32) NOT NULL DEFAULT 'device_switch', "
        "tuya_home_id VARCHAR(64) NULL, "
        "tuya_scene_id VARCHAR(128) NULL, "
        "desired_state BOOLEAN NOT NULL DEFAULT TRUE, "
        "schedule_time VARCHAR(5) NOT NULL, "
        "weekdays_csv VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5,6,7', "
        "is_enabled BOOLEAN NOT NULL DEFAULT TRUE, "
        "notes TEXT NULL, "
        "last_trigger_slot VARCHAR(32) NULL, "
        "last_run_at TIMESTAMP NULL, "
        "last_run_status VARCHAR(32) NULL, "
        "last_result_summary TEXT NULL, "
        "created_at TIMESTAMP DEFAULT NOW(), "
        "updated_at TIMESTAMP DEFAULT NOW()"
        ")",
        "ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS action_kind VARCHAR(32) NOT NULL DEFAULT 'device_switch'",
        "ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS tuya_home_id VARCHAR(64)",
        "ALTER TABLE automation_rules ADD COLUMN IF NOT EXISTS tuya_scene_id VARCHAR(128)",
        "ALTER TABLE automation_rules ALTER COLUMN device_id DROP NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_automation_rules_action_kind ON automation_rules(action_kind)",
        "CREATE INDEX IF NOT EXISTS ix_automation_rules_device_id ON automation_rules(device_id)",
        "CREATE INDEX IF NOT EXISTS ix_automation_rules_schedule_time ON automation_rules(schedule_time)",
        "CREATE INDEX IF NOT EXISTS ix_automation_rules_is_enabled ON automation_rules(is_enabled)",
        "CREATE TABLE IF NOT EXISTS automation_run_logs ("
        "id SERIAL PRIMARY KEY, "
        "rule_id INTEGER NOT NULL REFERENCES automation_rules(id) ON DELETE CASCADE, "
        "device_id INTEGER NULL REFERENCES devices(id) ON DELETE CASCADE, "
        "trigger VARCHAR(32) NOT NULL, "
        "status VARCHAR(32) NOT NULL, "
        "requested_at TIMESTAMP NOT NULL, "
        "result_summary TEXT NULL, "
        "error_message TEXT NULL, "
        "created_at TIMESTAMP DEFAULT NOW()"
        ")",
        "CREATE INDEX IF NOT EXISTS ix_automation_run_logs_rule_id ON automation_run_logs(rule_id)",
        "CREATE INDEX IF NOT EXISTS ix_automation_run_logs_device_id ON automation_run_logs(device_id)",
        "CREATE INDEX IF NOT EXISTS ix_automation_run_logs_trigger ON automation_run_logs(trigger)",
        "CREATE INDEX IF NOT EXISTS ix_automation_run_logs_status ON automation_run_logs(status)",
        "CREATE INDEX IF NOT EXISTS ix_automation_run_logs_requested_at ON automation_run_logs(requested_at)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
