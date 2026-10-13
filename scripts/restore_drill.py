"""Restore the newest backup into a clean directory and check it. Run via `make restore-drill`.

Proves a backup is usable, not just present: the file is copied (never modified) into a fresh
temporary directory, then opened the way the app opens it. Checks: SQLite integrity, foreign keys,
that the migrations recorded in the backup match the files in this checkout, that the full-text
index agrees with the entries table, that at least one admin can still log in, and row counts of
every table against the backup file itself (plus any --expect NAME=COUNT from the live app).

    restore_drill.py                          newest app-*.db in $BACKUP_DIR (or data/backups)
    restore_drill.py --backup-dir DIR         newest app-*.db in DIR
    restore_drill.py --backup FILE            exactly this file
    restore_drill.py --expect entries=120     fail unless the restored table has that many rows
    restore_drill.py --keep                   leave the restored copy for inspection

Exit status 0 only if every check passes. The source backup is opened read-only and untouched.
"""

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import sqlite_vec

from app.db import connect
from app.migrate import MIGRATIONS_DIR

BACKUP_GLOB = "app-*.db"


def newest_backup(directory: Path) -> Path:
    """Names carry a sortable UTC timestamp (backup.sh), so a name sort is a date sort."""
    found = sorted(directory.glob(BACKUP_GLOB))
    if not found:
        raise SystemExit(f"no {BACKUP_GLOB} files in {directory}")
    return found[-1]


def open_source(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: no -wal or -shm files are created next to the backup."""
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def table_names(conn: sqlite3.Connection) -> list[str]:
    """Every table, virtual ones included. Shadow tables of FTS and vec0 are skipped: their rows are
    an implementation detail and the virtual table itself is what the app reads."""
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    virtual = [r["name"] for r in rows if (r["sql"] or "").upper().startswith("CREATE VIRTUAL")]
    return sorted(
        r["name"]
        for r in rows
        if not any(r["name"].startswith(v + "_") for v in virtual)
        and r["name"] != "schema_migrations"
    )


def count_rows(conn: sqlite3.Connection, names: list[str]) -> dict[str, int]:
    # Table names come from sqlite_master of the file being checked, not from user input.
    return {n: conn.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}  # noqa: S608


class Report:
    def __init__(self) -> None:
        self.failed = False

    def ok(self, message: str) -> None:
        print(f"  ok    {message}")

    def fail(self, message: str) -> None:
        self.failed = True
        print(f"  FAIL  {message}")


def check_migrations(conn: sqlite3.Connection, report: Report) -> None:
    has = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if not has:
        report.fail("no schema_migrations table: this is not a Jifunze database")
        return
    applied = {r["version"]: r["checksum"] for r in conn.execute("SELECT * FROM schema_migrations")}
    files = {p.name[:4]: p for p in sorted(MIGRATIONS_DIR.glob("*.sql"))}
    bad = [
        v
        for v, checksum in applied.items()
        if v not in files
        or hashlib.sha256(files[v].read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        != checksum
    ]
    if bad:
        report.fail(f"migration(s) {sorted(bad)} differ from the files in this checkout")
        return
    pending = sorted(set(files) - set(applied))
    report.ok(f"{len(applied)} migration(s) recorded and matching the checkout")
    if pending:
        print(f"  note  backup predates migration(s) {pending}; the next deploy applies them")


def check_restored(path: Path, source_counts: dict[str, int], expect: dict[str, int]) -> Report:
    report = Report()
    try:
        _check_restored(path, source_counts, expect, report)
    except sqlite3.DatabaseError as exc:
        report.fail(f"the restored copy could not be read: {exc}")
    return report


def _check_restored(
    path: Path, source_counts: dict[str, int], expect: dict[str, int], report: Report
) -> None:
    conn = connect(path)  # the app's own opener: pragmas and sqlite-vec loaded (this copy is ours)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchall()
        if [r[0] for r in result] == ["ok"]:
            report.ok("PRAGMA integrity_check")
        else:
            report.fail("integrity_check: " + "; ".join(str(r[0]) for r in result[:5]))

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            report.fail(f"foreign_key_check: {len(violations)} violation(s)")
        else:
            report.ok("PRAGMA foreign_key_check")

        check_migrations(conn, report)

        try:
            # rank = 1 also compares the index with the entries table (SQLite 3.44+; Pi: 3.46).
            conn.execute("INSERT INTO entries_fts(entries_fts, rank) VALUES ('integrity-check', 1)")
            report.ok("full-text index agrees with entries")
        except sqlite3.DatabaseError as exc:
            report.fail(f"full-text index does not match entries: {exc}")

        names = table_names(conn)
        restored = count_rows(conn, names)
        for name in names:
            if restored[name] != source_counts.get(name):
                report.fail(
                    f"{name}: backup has {source_counts.get(name)} rows, restored {restored[name]}"
                )
            else:
                report.ok(f"{name}: {restored[name]} rows")
        for name, wanted in expect.items():
            if restored.get(name) != wanted:
                report.fail(
                    f"--expect {name}={wanted}, but the restored copy has {restored.get(name)}"
                )
        if restored.get("entries", 0) == 0:
            print("  note  there are no entries in this backup")

        admins = conn.execute("SELECT count(*) FROM users WHERE role = 'admin'").fetchone()[0]
        if admins:
            report.ok(f"{admins} admin account(s): someone can sign in and review")
        else:
            report.fail("no admin account in the backup")
    finally:
        conn.close()


def parse_expect(items: list[str]) -> dict[str, int]:
    expect = {}
    for item in items:
        name, _, value = item.partition("=")
        if not name or not value.isdigit():
            raise SystemExit(f"--expect wants NAME=COUNT, got {item!r}")
        expect[name] = int(value)
    return expect


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a Jifunze backup and check it")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--backup", type=Path, help="restore exactly this file")
    which.add_argument("--backup-dir", type=Path, help="restore the newest app-*.db in here")
    parser.add_argument("--expect", action="append", default=[], metavar="NAME=COUNT")
    parser.add_argument("--keep", action="store_true", help="keep the restored copy")
    args = parser.parse_args()

    backup = args.backup or newest_backup(
        args.backup_dir or Path(os.environ.get("BACKUP_DIR", "data/backups"))
    )
    if not backup.is_file():
        raise SystemExit(f"not a file: {backup}")
    expect = parse_expect(args.expect)

    work = Path(tempfile.mkdtemp(prefix="jifunze-restore-"))  # mode 0700, empty, new
    try:
        print(f"restoring {backup} ({backup.stat().st_size} bytes) into {work}")
        source = open_source(backup)
        try:
            source_counts = count_rows(source, table_names(source))
        except sqlite3.DatabaseError as exc:
            print(f"  FAIL  the backup cannot be read: {exc}")
            return 1
        finally:
            source.close()
        restored = work / "app.db"
        shutil.copyfile(backup, restored)
        report = check_restored(restored, source_counts, expect)
    finally:
        if args.keep:
            print(f"kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print("RESTORE DRILL FAILED" if report.failed else "restore drill passed")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
