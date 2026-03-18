from __future__ import annotations

from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path('/app/backups/db')


def _resolve_backup_path(name: str) -> Path:
    raw = (name or '').strip()
    if not raw:
        raise ValueError('Имя файла бэкапа не указано.')
    if Path(raw).name != raw:
        raise ValueError('Некорректное имя файла бэкапа.')
    if not raw.endswith('.dump'):
        raise ValueError('Удалять можно только .dump файлы из каталога бэкапов.')
    return BACKUP_DIR / raw


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


def delete_backup(name: str) -> bool:
    path = _resolve_backup_path(name)
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True
