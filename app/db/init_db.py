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
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
