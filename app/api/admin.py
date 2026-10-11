"""Admin-only operational status. Read-only, and it returns counts and times, never content."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.deps import get_db, get_settings, require_admin
from app.config import Settings
from app.db import Database

router = APIRouter()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def last_backup_at(stamp: str) -> str | None:
    """The backup job touches this file when it finishes; its mtime is the last backup time."""
    try:
        mtime = Path(stamp).stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/api/admin/status")
def status(
    admin: Annotated[dict, Depends(require_admin)],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    path = Path(db.path)
    with db.read() as conn:
        pending = conn.execute("SELECT COUNT(*) FROM entries WHERE embedded_at IS NULL").fetchone()[
            0
        ]
        failed_logins = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'login.failure'"
            " AND at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')"
        ).fetchone()[0]
    return {
        "database": {
            "bytes": _size(path),
            "wal_bytes": _size(path.with_name(path.name + "-wal")),
        },
        "embeddings": {"pending": pending},
        "backup": {"last_backup_at": last_backup_at(settings.backup_stamp_path)},
        "audit": {"failed_logins_24h": failed_logins},
    }
