from __future__ import annotations

from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path('/app/backups/db')


def list_backups() -> list[dict]:
    items: list[dict] = []
    if not BACKUP_DIR.exists():
        return items
    for path in sorted(BACKUP_DIR.glob('*.dump'), reverse=True):
        stat = path.stat()
        items.append(
            {
                'name': path.name,
                'size_bytes': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'modified_at': datetime.utcfromtimestamp(stat.st_mtime).replace(microsecond=0),
            }
        )
    return items
