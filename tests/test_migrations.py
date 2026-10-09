import pytest

from app.db import connect
from app.migrate import MIGRATIONS_DIR, MigrationError, apply_migrations


def _tables(conn):
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_applies_to_empty_database(tmp_path):
    conn = connect(tmp_path / "a.db")
    applied = apply_migrations(conn)
    assert applied == ["0001_init.sql"]
    assert {"users", "sessions", "entries", "entry_history", "user_progress"} <= _tables(conn)
    assert {"noun_classes", "verb_paradigms", "reminders", "schema_migrations"} <= _tables(conn)
    assert {"entries_fts", "entry_vec"} <= _tables(conn)


def test_second_run_is_a_no_op(tmp_path):
    conn = connect(tmp_path / "a.db")
    apply_migrations(conn)
    assert apply_migrations(conn) == []
    assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1


def test_editing_an_applied_migration_is_refused(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_one.sql").write_text("CREATE TABLE a (x);")
    conn = connect(tmp_path / "a.db")
    apply_migrations(conn, migrations)
    (migrations / "0001_one.sql").write_text("CREATE TABLE a (x, y);")
    with pytest.raises(MigrationError, match="edited"):
        apply_migrations(conn, migrations)


def test_failed_migration_rolls_back_and_is_not_recorded(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_bad.sql").write_text("CREATE TABLE a (x); SELECT * FROM missing_table;")
    conn = connect(tmp_path / "a.db")
    with pytest.raises(MigrationError):
        apply_migrations(conn, migrations)
    assert "a" not in _tables(conn)
    assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0


def test_missing_applied_file_is_refused(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_one.sql").write_text("CREATE TABLE a (x);")
    conn = connect(tmp_path / "a.db")
    apply_migrations(conn, migrations)
    (migrations / "0001_one.sql").unlink()
    with pytest.raises(MigrationError, match="missing"):
        apply_migrations(conn, migrations)


def test_real_migration_directory_is_named_correctly():
    assert (MIGRATIONS_DIR / "0001_init.sql").exists()
