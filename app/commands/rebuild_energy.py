from __future__ import annotations

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.services.energy_rebuild_service import rebuild_energy_aggregates_from_snapshots


def main() -> None:
    init_db()
    with SessionLocal() as db:
        result = rebuild_energy_aggregates_from_snapshots(db)
    print(result)


if __name__ == '__main__':
    main()
