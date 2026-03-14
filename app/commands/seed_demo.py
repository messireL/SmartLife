from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.services.sync_service import sync_from_provider


def main() -> None:
    init_db()
    with SessionLocal() as db:
        result = sync_from_provider(db)
        print(result)


if __name__ == "__main__":
    main()
