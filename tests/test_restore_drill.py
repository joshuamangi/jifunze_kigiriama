"""scripts/restore_drill.py against real backups made the way deploy/backup.sh makes them."""

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "restore_drill.py"

# Verified numbers only (CLAUDE.md): never invented Kigiriama.
WORDS = [("mwenga", "one"), ("hiri", "two"), ("hahu", "three")]


@pytest.fixture
def live(db, make_user):
    """A populated database: one admin, one member, three entries."""
    admin = make_user("amina", role="admin")
    make_user("baraka", role="member")
    with db.write() as conn:
        for giriama, english in WORDS:
            conn.execute(
                "INSERT INTO entries (giriama, english, category, source_type,"
                " verification_status, created_by)"
                " VALUES (?, ?, 'numbers', 'own', 'unverified', ?)",
                (giriama, english, admin),
            )
    return db


def make_backup(db, directory: Path, name: str) -> Path:
    """What `sqlite3 .backup` does: a consistent copy of a live WAL database."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    dest = sqlite3.connect(target)
    with db.read() as conn:
        conn.backup(dest)
    dest.close()
    return target


def run(*args):
    return subprocess.run(  # noqa: S603 - fixed argv, our own script
        [sys.executable, "-I", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT), "PATH": ""},
        check=False,
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_good_backup_passes_and_reports_row_counts(live, tmp_path):
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    result = run("--backup", str(backup), "--expect", "entries=3", "--expect", "users=2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "restore drill passed" in result.stdout
    assert "entries: 3 rows" in result.stdout
    assert "1 admin account(s)" in result.stdout
    assert "full-text index agrees" in result.stdout


def test_the_newest_backup_in_a_directory_is_chosen(live, tmp_path):
    directory = tmp_path / "b"
    make_backup(live, directory, "app-20261001T030000Z.db")
    with live.write() as conn:
        conn.execute(
            "INSERT INTO entries (giriama, english, category, source_type, verification_status)"
            " VALUES ('kumi', 'ten', 'numbers', 'own', 'unverified')"
        )
    newest = make_backup(live, directory, "app-20261013T030000Z.db")
    result = run("--backup-dir", str(directory))
    assert result.returncode == 0, result.stdout
    assert newest.name in result.stdout
    assert "entries: 4 rows" in result.stdout


def test_the_source_backup_is_left_untouched(live, tmp_path):
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    before = sha(backup)
    assert run("--backup", str(backup)).returncode == 0
    assert sha(backup) == before
    assert sorted(p.name for p in backup.parent.iterdir()) == [backup.name]


def test_the_restored_copy_is_removed_unless_kept(live, tmp_path):
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    gone = run("--backup", str(backup))
    kept = run("--backup", str(backup), "--keep")
    gone_dir = next(line for line in gone.stdout.splitlines() if line.startswith("restoring"))
    assert "kept:" not in gone.stdout and "into " in gone_dir
    kept_dir = Path(kept.stdout.split("kept: ")[1].splitlines()[0])
    try:
        assert (kept_dir / "app.db").is_file()
    finally:
        import shutil

        shutil.rmtree(kept_dir, ignore_errors=True)


def test_a_wrong_expected_count_fails(live, tmp_path):
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    result = run("--backup", str(backup), "--expect", "entries=99")
    assert result.returncode == 1
    assert "--expect entries=99" in result.stdout
    assert "RESTORE DRILL FAILED" in result.stdout


def test_a_backup_with_no_admin_fails(live, tmp_path):
    with live.write() as conn:
        conn.execute("UPDATE users SET role = 'member'")
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    result = run("--backup", str(backup))
    assert result.returncode == 1
    assert "no admin account" in result.stdout


def test_a_corrupt_backup_fails(live, tmp_path):
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    data = bytearray(backup.read_bytes())
    data[4096 * 2 : 4096 * 2 + 64] = b"\xff" * 64  # damage a page after the header
    backup.write_bytes(bytes(data))
    result = run("--backup", str(backup))
    assert result.returncode == 1, result.stdout
    assert "FAIL" in result.stdout


def test_not_a_database_fails(tmp_path):
    junk = tmp_path / "app-20261013T030000Z.db"
    junk.write_bytes(b"this is not sqlite" * 100)
    result = run("--backup", str(junk))
    assert result.returncode == 1


def test_a_backup_made_with_an_edited_migration_fails(live, tmp_path):
    with live.write() as conn:
        conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = '0001'")
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    result = run("--backup", str(backup))
    assert result.returncode == 1
    assert "differ from the files in this checkout" in result.stdout


def test_a_stale_full_text_index_fails(live, tmp_path):
    with live.write() as conn:
        # Remove an index row without going through the trigger: the index now disagrees.
        conn.execute(
            "INSERT INTO entries_fts (entries_fts, rowid, english, giriama)"
            " VALUES ('delete', 1, 'one', 'mwenga')"
        )
    backup = make_backup(live, tmp_path / "b", "app-20261013T030000Z.db")
    result = run("--backup", str(backup))
    assert result.returncode == 1
    assert "full-text index does not match" in result.stdout


def test_an_empty_backup_directory_is_an_error(tmp_path):
    (tmp_path / "empty").mkdir()
    result = run("--backup-dir", str(tmp_path / "empty"))
    assert result.returncode != 0
    assert "no app-*.db files" in result.stderr
