import pytest

from app.db import connect
from app.migrate import MIGRATIONS_DIR, MigrationError, apply_migrations, pending_migrations


def _tables(conn):
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_applies_to_empty_database(tmp_path):
    conn = connect(tmp_path / "a.db")
    applied = apply_migrations(conn)
    assert applied == ["0001_init.sql", "0002_entry_decline.sql"]
    assert {"users", "sessions", "entries", "entry_history", "user_progress"} <= _tables(conn)
    assert {"noun_classes", "verb_paradigms", "reminders", "schema_migrations"} <= _tables(conn)
    assert {"entries_fts", "entry_vec"} <= _tables(conn)


def test_second_run_is_a_no_op(tmp_path):
    conn = connect(tmp_path / "a.db")
    apply_migrations(conn)
    assert apply_migrations(conn) == []
    assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2


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


def test_pending_migrations_lists_what_has_not_been_applied(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_one.sql").write_text("CREATE TABLE a (x);")
    (migrations / "0002_two.sql").write_text("CREATE TABLE b (x);")
    conn = connect(tmp_path / "a.db")
    assert pending_migrations(conn, migrations) == ["0001_one.sql", "0002_two.sql"]  # no table yet
    apply_migrations(conn, migrations)
    assert pending_migrations(conn, migrations) == []
    (migrations / "0003_three.sql").write_text("CREATE TABLE c (x);")
    assert pending_migrations(conn, migrations) == ["0003_three.sql"]


def test_app_refuses_to_start_on_an_out_of_date_database(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.db import Database
    from app.main import create_app

    # Reproduces the real failure: a dev database that stopped at 0001 while the code needs 0002.
    old = tmp_path / "migrations"
    old.mkdir()
    (old / "0001_init.sql").write_text((MIGRATIONS_DIR / "0001_init.sql").read_text())
    path = tmp_path / "stale.db"
    setup = connect(path)
    apply_migrations(setup, old)
    setup.close()

    db = Database(path, readers=1)
    app = create_app(Settings.from_env({"ARGON2_MEMORY_KIB": "8", "ARGON2_TIME_COST": "1"}), db)
    with pytest.raises(RuntimeError, match="make migrate"), TestClient(app):
        pass
    db.close()
