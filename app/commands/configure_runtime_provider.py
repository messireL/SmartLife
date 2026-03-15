from __future__ import annotations

import argparse

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.services.runtime_config_service import configure_demo_provider, configure_tuya_cloud


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Store SmartLife runtime provider settings in PostgreSQL")
    sub = parser.add_subparsers(dest="command", required=True)

    tuya = sub.add_parser("tuya", help="Save Tuya Cloud settings to DB")
    tuya.add_argument("--base-url", required=True)
    tuya.add_argument("--access-id", required=True)
    tuya.add_argument("--access-secret", required=True)
    tuya.add_argument("--project-code", default="")

    sub.add_parser("demo", help="Switch provider to demo in DB")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    init_db()
    with SessionLocal() as db:
        if args.command == "tuya":
            runtime = configure_tuya_cloud(
                db,
                base_url=args.base_url,
                access_id=args.access_id,
                access_secret=args.access_secret,
                project_code=args.project_code,
            )
            print(f"Saved Tuya Cloud config to DB: provider={runtime.provider}, base_url={runtime.tuya_base_url}, project_code={runtime.tuya_project_code or '-'}")
            return
        runtime = configure_demo_provider(db)
        print(f"Saved provider to DB: {runtime.provider}")


if __name__ == "__main__":
    main()
