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
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS product_id VARCHAR(128)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS product_name VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS icon_url VARCHAR(512)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS switch_on BOOLEAN",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_power_w NUMERIC(12,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_voltage_v NUMERIC(12,2)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS current_a NUMERIC(12,3)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS energy_total_kwh NUMERIC(14,3)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS fault_code VARCHAR(255)",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_status_at TIMESTAMP",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_status_payload TEXT",
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
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
