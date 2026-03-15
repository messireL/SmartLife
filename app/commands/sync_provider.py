from app.db.models import SyncRunTrigger
from app.services.sync_runner import run_sync_job


def main() -> None:
    result = run_sync_job(trigger=SyncRunTrigger.CLI, fail_if_running=True)
    print(result)


if __name__ == "__main__":
    main()
