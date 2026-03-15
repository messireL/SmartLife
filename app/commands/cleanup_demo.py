from __future__ import annotations

from app.db.session import SessionLocal
from app.services.device_admin_service import purge_demo_devices


def main() -> None:
    with SessionLocal() as db:
        removed = purge_demo_devices(db)
    print(f"Removed demo devices: {removed}")


if __name__ == "__main__":
    main()
