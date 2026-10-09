"""Seed the verified numbers (Omniglot) listed in CLAUDE.md. Nothing else may be seeded.

Run with `make seed` after `make migrate`. Safe to run twice.
"""

import sqlite3

from app.config import Settings
from app.db import connect

# (giriama, english). Verified words only; do not add to this list without a source.
VERIFIED_NUMBERS = [
    ("mwenga", "one"),
    ("hiri", "two"),
    ("hahu", "three"),
    ("inne", "four"),
    ("tsano", "five"),
    ("handahu", "six"),
    ("fungahe", "seven"),
    ("nane", "eight"),
    ("chenda", "nine"),
    ("kumi", "ten"),
    ("kumi na hahu", "thirteen"),
    ("mirongo miiri", "twenty"),
]
CATEGORY = "numbers"


def seed(conn: sqlite3.Connection) -> int:
    """Insert missing seed rows; return how many were added."""
    added = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for giriama, english in VERIFIED_NUMBERS:
            exists = conn.execute(
                "SELECT 1 FROM entries WHERE giriama = ? AND english = ?", (giriama, english)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO entries (giriama, english, category, source_type,"
                " verification_status) VALUES (?, ?, ?, 'dictionary', 'unverified')",
                (giriama, english, CATEGORY),
            )
            added += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return added


def main() -> None:
    conn = connect(Settings.from_env().database_path)
    try:
        print(f"seeded {seed(conn)} entries")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
