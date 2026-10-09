import sqlite3

import pytest

from app.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db", readers=2)
    yield database
    database.close()


def _pragma(conn, name):
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def test_pragmas_on_write_and_read_connections(db):
    with db.write() as w, db.read() as r:
        for conn in (w, r):
            assert _pragma(conn, "journal_mode") == "wal"
            assert _pragma(conn, "foreign_keys") == 1
            assert _pragma(conn, "busy_timeout") == 5000
            assert _pragma(conn, "synchronous") == 1  # NORMAL


def test_read_connections_cannot_write(db):
    with db.write() as w:
        w.execute("CREATE TABLE t (x)")
    with db.read() as r, pytest.raises(sqlite3.OperationalError):
        r.execute("INSERT INTO t VALUES (1)")


def test_write_rolls_back_on_error(db):
    with db.write() as w:
        w.execute("CREATE TABLE t (x)")
    with pytest.raises(RuntimeError), db.write() as w:
        w.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    with db.read() as r:
        assert r.execute("SELECT count(*) FROM t").fetchone()[0] == 0


def test_sqlite_vec_is_loaded(db):
    with db.read() as r:
        assert r.execute("SELECT vec_version()").fetchone()[0].startswith("v")
