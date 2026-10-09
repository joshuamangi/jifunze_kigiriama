import json
import sqlite3
import struct

import pytest

from app.seed import CATEGORY, VERIFIED_NUMBERS, seed


def _plan(conn, sql, params=()):
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return " | ".join(r["detail"] for r in rows)


def test_due_items_query_uses_due_index(conn):
    plan = _plan(
        conn,
        "SELECT entry_id FROM user_progress WHERE user_id = ? AND due_date <= ? ORDER BY due_date",
        (1, "2026-01-01"),
    )
    assert "idx_user_progress_due" in plan
    assert "TEMP B-TREE" not in plan  # ordered by the index, no sort step


def test_category_filter_uses_category_index(conn):
    plan = _plan(
        conn,
        "SELECT id FROM entries WHERE category = ? ORDER BY created_at DESC",
        ("numbers",),
    )
    assert "idx_entries_category_created" in plan
    assert "TEMP B-TREE" not in plan


def test_pending_queue_uses_partial_index(conn):
    plan = _plan(
        conn,
        "SELECT id FROM entries WHERE verification_status = 'pending' ORDER BY created_at",
    )
    assert "idx_entries_pending" in plan
    assert "TEMP B-TREE" not in plan


def test_username_lookup_uses_unique_index(conn):
    plan = _plan(conn, "SELECT id FROM users WHERE username = ? COLLATE NOCASE", ("Amina",))
    assert "idx_users_username" in plan


def test_only_the_named_indexes_exist(conn):
    names = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
    }
    assert names == {
        "idx_users_username",
        "idx_sessions_user",
        "idx_sessions_expires",
        "idx_entries_category_created",
        "idx_entries_pending",
        "idx_entry_history_entry",
        "idx_user_progress_due",
    }


def test_username_is_unique_ignoring_case(conn):
    conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES ('Amina', 'x', 'member')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES ('amina', 'x', 'member')"
        )


def test_progress_row_cannot_reference_missing_entry(conn):
    conn.execute("INSERT INTO users (username, password_hash, role) VALUES ('a', 'x', 'member')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_progress (user_id, entry_id, due_date) VALUES (1, 999, '2026-01-01')"
        )


def test_progress_state_is_not_on_entries(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)")}
    assert not cols & {"interval", "ease_factor", "due_date", "last_reviewed"}
    assert "embedded_at" in cols


def test_enum_columns_are_checked(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entries (giriama, english, category, source_type, verification_status)"
            " VALUES ('hiri', 'two', 'numbers', 'guess', 'pending')"
        )


def test_grammar_rules_must_be_valid_json(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO noun_classes (label, rule_json) VALUES ('x', 'not json')")
    conn.execute(
        "INSERT INTO noun_classes (label, rule_json) VALUES ('x', ?)", (json.dumps({"a": 1}),)
    )


def _vec(*values):
    padded = list(values) + [0.0] * (384 - len(values))
    return struct.pack("384f", *padded)


def test_vec0_insert_and_nearest_neighbour(conn):
    conn.execute("INSERT INTO entry_vec (entry_id, embedding) VALUES (1, ?)", (_vec(1.0, 0.0),))
    conn.execute("INSERT INTO entry_vec (entry_id, embedding) VALUES (2, ?)", (_vec(0.0, 1.0),))
    rows = conn.execute(
        "SELECT entry_id, distance FROM entry_vec WHERE embedding MATCH ? AND k = 1",
        (_vec(0.9, 0.1),),
    ).fetchall()
    assert [r["entry_id"] for r in rows] == [1]


def test_seed_adds_only_verified_numbers_and_is_idempotent(conn):
    assert seed(conn) == len(VERIFIED_NUMBERS)
    assert seed(conn) == 0
    rows = conn.execute(
        "SELECT giriama, english, category, source_type, verification_status FROM entries"
    ).fetchall()
    assert {r["giriama"] for r in rows} == {
        "mwenga", "hiri", "hahu", "inne", "tsano", "handahu",
        "fungahe", "nane", "chenda", "kumi", "kumi na hahu", "mirongo miiri",
    }  # fmt: skip
    assert all(
        (r["category"], r["source_type"], r["verification_status"])
        == (CATEGORY, "dictionary", "unverified")
        for r in rows
    )


def test_keyword_search_finds_seeded_entry(conn):
    seed(conn)
    rows = conn.execute("SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'thirteen'")
    ids = [r["rowid"] for r in rows]
    giriama = conn.execute("SELECT giriama FROM entries WHERE id = ?", (ids[0],)).fetchone()[0]
    assert giriama == "kumi na hahu"


def test_fts_follows_edits(conn):
    seed(conn)
    conn.execute("UPDATE entries SET english = 'ten (count)' WHERE giriama = 'kumi'")
    assert (
        conn.execute("SELECT count(*) FROM entries_fts WHERE entries_fts MATCH 'count'").fetchone()[
            0
        ]
        == 1
    )
    conn.execute("DELETE FROM entries WHERE giriama = 'kumi'")
    assert (
        conn.execute("SELECT count(*) FROM entries_fts WHERE entries_fts MATCH 'count'").fetchone()[
            0
        ]
        == 0
    )
