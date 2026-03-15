from __future__ import annotations

import json

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.services.runtime_diagnostics_service import get_runtime_diagnostics


def main() -> None:
    init_db()
    with SessionLocal() as db:
        diagnostics = get_runtime_diagnostics(db)
    print(json.dumps(diagnostics.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
