"""Numbered SQL migration runner. Run with `make migrate`.

Applied migrations are recorded with a SHA-256 checksum; editing an applied file is refused.
Migrations must stay backward compatible (add first, remove in a later release) so that a code
rollback never needs a database restore.
"""

import hashlib
import re
import sqlite3
from pathlib import Path

from app.config import Settings
from app.db import connect

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    pass


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def pending_migrations(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Names of migration files that have not been applied yet (read-only)."""
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    applied = (
        {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        if has_table
        else set()
    )
    return [p.name for p in sorted(directory.glob("*.sql")) if p.name[:4] not in applied]


def apply_migrations(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in order; return the names applied this run."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " checksum TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
    )
    applied = {r["version"]: r for r in conn.execute("SELECT * FROM schema_migrations")}
    files = sorted(p for p in directory.glob("*.sql"))
    for path in files:
        if not _NAME.match(path.name):
            raise MigrationError(f"bad migration file name: {path.name}")
    on_disk = {p.name[:4] for p in files}
    missing = set(applied) - on_disk
    if missing:
        raise MigrationError(f"applied migration file(s) missing: {sorted(missing)}")

    done: list[str] = []
    for path in files:
        version = path.name[:4]
        sql = path.read_text(encoding="utf-8")
        checksum = _checksum(sql)
        if version in applied:
            if applied[version]["checksum"] != checksum:
                raise MigrationError(
                    f"{path.name} was edited after it was applied; add a new migration instead"
                )
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\n")
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                (version, path.name, checksum),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(f"{path.name} failed and was rolled back: {exc}") from exc
        done.append(path.name)
    return done


def main() -> None:
    settings = Settings.from_env()
    conn = connect(settings.database_path)
    try:
        done = apply_migrations(conn)
    finally:
        conn.close()
    print("applied: " + ", ".join(done) if done else "database is up to date")


if __name__ == "__main__":
    main()
