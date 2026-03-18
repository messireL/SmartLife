from __future__ import annotations

from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path('/app/backups/db')
BACKUP_POLICY_FILE = BACKUP_DIR / '.retention.env'


def _resolve_backup_path(name: str) -> Path:
    raw = (name or '').strip()
    if not raw:
        raise ValueError('Имя файла бэкапа не указано.')
    if Path(raw).name != raw:
        raise ValueError('Некорректное имя файла бэкапа.')
    if not raw.endswith('.dump'):
        raise ValueError('Удалять можно только .dump файлы из каталога бэкапов.')
    return BACKUP_DIR / raw


def write_backup_policy(*, keep_last: int, auto_prune_enabled: bool) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    keep_last = max(0, min(500, int(keep_last)))
    content = (
        '# SmartLife backup retention policy\n'
        f'KEEP_LAST={keep_last}\n'
        f'AUTO_PRUNE_ENABLED={"yes" if auto_prune_enabled else "no"}\n'
    )
    BACKUP_POLICY_FILE.write_text(content, encoding='utf-8')


def list_backups() -> list[dict]:
    items: list[dict] = []
    if not BACKUP_DIR.exists():
        return items
    paths = sorted(
        BACKUP_DIR.glob('*.dump'),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in paths:
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


def filter_backups(backups: list[dict], query: str = '') -> list[dict]:
    needle = (query or '').strip().lower()
    if not needle:
        return list(backups)
    return [item for item in backups if needle in str(item.get('name') or '').lower()]


def summarize_backups(backups: list[dict]) -> dict[str, float | int]:
    total_bytes = sum(int(item.get('size_bytes') or 0) for item in backups)
    return {
        'count': len(backups),
        'total_bytes': total_bytes,
        'total_mb': round(total_bytes / (1024 * 1024), 2),
    }


def get_prunable_backups(backups: list[dict], *, keep_last: int) -> list[dict]:
    keep_last = max(0, int(keep_last))
    if keep_last <= 0:
        return []
    return list(backups[keep_last:])


def prune_backups(*, keep_last: int) -> dict[str, object]:
    keep_last = max(0, int(keep_last))
    if keep_last <= 0:
        return {'deleted_count': 0, 'deleted_names': [], 'freed_bytes': 0, 'freed_mb': 0.0}

    backups = list_backups()
    to_delete = get_prunable_backups(backups, keep_last=keep_last)
    deleted_names: list[str] = []
    freed_bytes = 0
    for item in to_delete:
        path = _resolve_backup_path(str(item.get('name') or ''))
        if path.exists() and path.is_file():
            freed_bytes += int(item.get('size_bytes') or 0)
            path.unlink()
            deleted_names.append(path.name)
    return {
        'deleted_count': len(deleted_names),
        'deleted_names': deleted_names,
        'freed_bytes': freed_bytes,
        'freed_mb': round(freed_bytes / (1024 * 1024), 2),
    }


def delete_backup(name: str) -> bool:
    path = _resolve_backup_path(name)
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True
