"""Entries, moderation and history.

Moderation reuses verification_status: member submissions start 'pending' and stay invisible to
other members until an admin approves. A declined entry keeps status 'pending' but has
declined_at set, so it stays hidden too. Every real change writes an entry_history row.

NOTE: entries.english is the only text that is ever embedded for semantic search (Stage 5).
Kigiriama text (entries.giriama) must never reach an embedder. Nothing is embedded here; an
edit to `english` only clears embedded_at so the worker will redo that entry later.
"""

import re
import sqlite3
from typing import Literal, get_args

from fastapi import HTTPException

from app.db import Database

CategoryId = Literal["greetings", "family", "numbers", "proverbs", "food"]
SourceType = Literal["own", "dictionary", "proverb", "scripture"]
Status = Literal["pending", "unverified", "self_corrected", "native_verified"]

CATEGORY_IDS: tuple[str, ...] = get_args(CategoryId)
CATEGORY_LABELS = {
    "greetings": "Greetings",
    "family": "Family",
    "numbers": "Numbers",
    "proverbs": "Proverbs",
    "food": "Food",
}
CONTENT_FIELDS = ("giriama", "english", "category", "source_type")
PATCHABLE = CONTENT_FIELDS + ("verification_status",)

# An entry is visible to the caller when they are an admin, its author, or it is approved.
VISIBLE = "(:admin = 1 OR e.created_by = :uid OR e.verification_status != 'pending')"
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

_SELECT = (
    "SELECT e.id, e.giriama, e.english, e.category, e.source_type, e.verification_status,"
    " e.created_by, u.username AS author, e.created_at, e.updated_at, e.declined_at"
    " FROM entries e LEFT JOIN users u ON u.id = e.created_by"
)
_TOKEN = re.compile(r"[^\W_]+")
MAX_QUERY_TOKENS = 8
MAX_TOKEN_LENGTH = 64


def _scope(user: dict) -> dict:
    return {"admin": 1 if user["role"] == "admin" else 0, "uid": user["id"]}


def _public(row: sqlite3.Row, user: dict) -> dict:
    entry = {
        "id": row["id"],
        "giriama": row["giriama"],
        "english": row["english"],
        "category": row["category"],
        "source_type": row["source_type"],
        "verification_status": row["verification_status"],
        "declined": row["declined_at"] is not None,
        "mine": row["created_by"] == user["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if user["role"] == "admin":
        entry["created_by"] = row["author"]
    return entry


def fts_query(text: str) -> str:
    """Turn free text into quoted prefix tokens so FTS5 operators and quotes in user input can
    neither raise a syntax error nor change the meaning of the query."""
    tokens = [t[:MAX_TOKEN_LENGTH] for t in _TOKEN.findall(text)][:MAX_QUERY_TOKENS]
    return " ".join(f'"{t}"*' for t in tokens)


def _visible_row(conn: sqlite3.Connection, user: dict, entry_id: int) -> sqlite3.Row:
    row = conn.execute(
        f"{_SELECT} WHERE e.id = :id AND {VISIBLE}", {**_scope(user), "id": entry_id}
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return row


def get_entry(db: Database, user: dict, entry_id: int) -> dict:
    with db.read() as conn:
        return _public(_visible_row(conn, user, entry_id), user)


def list_entries(
    db: Database, user: dict, category: str | None, q: str | None, limit: int, offset: int
) -> dict:
    where = [VISIBLE]
    params: dict = _scope(user)
    if category:
        where.append("e.category = :category")
        params["category"] = category
    if q and q.strip():
        match = fts_query(q)
        if not match:  # only punctuation: nothing can match
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        where.append("e.id IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH :match)")
        params["match"] = match
    clause = " AND ".join(where)
    with db.read() as conn:
        total = conn.execute(f"SELECT count(*) FROM entries e WHERE {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"{_SELECT} WHERE {clause} ORDER BY e.created_at DESC, e.id DESC"
            " LIMIT :limit OFFSET :offset",
            {**params, "limit": limit, "offset": offset},
        ).fetchall()
    return {
        "items": [_public(r, user) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def create_entry(db: Database, user: dict, data: dict) -> dict:
    status = "unverified" if user["role"] == "admin" else "pending"
    with db.write() as conn:
        cur = conn.execute(
            "INSERT INTO entries (giriama, english, category, source_type, verification_status,"
            " created_by) VALUES (:giriama, :english, :category, :source_type, :status, :uid)",
            {**data, "status": status, "uid": user["id"]},
        )
        return _public(_visible_row(conn, user, cur.lastrowid), user)


def _record_history(conn: sqlite3.Connection, row: sqlite3.Row, changed_by: int) -> None:
    conn.execute(
        "INSERT INTO entry_history (entry_id, changed_by, old_giriama, old_english, old_category,"
        " old_source_type, old_verification_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            changed_by,
            row["giriama"],
            row["english"],
            row["category"],
            row["source_type"],
            row["verification_status"],
        ),
    )


def update_entry(db: Database, user: dict, entry_id: int, patch: dict) -> dict:
    is_admin = user["role"] == "admin"
    with db.write() as conn:
        row = _visible_row(conn, user, entry_id)
        if not is_admin:
            if row["created_by"] != user["id"]:
                raise HTTPException(status_code=403, detail="you can only edit your own entries")
            if row["verification_status"] == "native_verified":
                raise HTTPException(status_code=403, detail="only an admin can edit this entry")
            if "verification_status" in patch:
                raise HTTPException(status_code=403, detail="only an admin can set the status")

        changes = {k: v for k, v in patch.items() if k in PATCHABLE and row[k] != v}
        if not changes:
            return _public(row, user)

        sets = dict(changes)
        clear_decline = False
        if not is_admin:
            # A member's edit always goes back to review, and resubmits a declined entry.
            sets["verification_status"] = "pending"
            clear_decline = row["declined_at"] is not None
        elif changes.get("verification_status") not in (None, "pending"):
            clear_decline = row["declined_at"] is not None

        _record_history(conn, row, user["id"])
        assignments = [f"{column} = :{column}" for column in sets]  # column names are whitelisted
        assignments.append(f"updated_at = {NOW}")
        if "english" in changes:
            assignments.append("embedded_at = NULL")  # Stage 5 worker re-embeds this entry
        if clear_decline:
            assignments += ["declined_at = NULL", "declined_by = NULL"]
        conn.execute(
            f"UPDATE entries SET {', '.join(assignments)} WHERE id = :id",
            {**sets, "id": entry_id},
        )
        return _public(_visible_row(conn, user, entry_id), user)


def entry_history(db: Database, user: dict, entry_id: int) -> list[dict]:
    with db.read() as conn:
        row = _visible_row(conn, user, entry_id)
        if user["role"] != "admin" and row["created_by"] != user["id"]:
            raise HTTPException(status_code=403, detail="history is limited to the author")
        rows = conn.execute(
            "SELECT h.*, u.username AS changed_by_name FROM entry_history h"
            " LEFT JOIN users u ON u.id = h.changed_by WHERE h.entry_id = ?"
            " ORDER BY h.changed_at DESC, h.id DESC",
            (entry_id,),
        ).fetchall()
    out = []
    for r in rows:
        item = {
            "changed_at": r["changed_at"],
            "changed_by_you": r["changed_by"] == user["id"],
            "old": {
                "giriama": r["old_giriama"],
                "english": r["old_english"],
                "category": r["old_category"],
                "source_type": r["old_source_type"],
                "verification_status": r["old_verification_status"],
            },
        }
        if user["role"] == "admin":
            item["changed_by"] = r["changed_by_name"]
        out.append(item)
    return out


# ---- moderation (admin only; the router enforces require_admin) -------------------------------
def review_queue(db: Database) -> dict:
    with db.read() as conn:
        rows = conn.execute(
            f"{_SELECT} WHERE e.verification_status = 'pending' AND e.declined_at IS NULL"
            " ORDER BY e.created_at, e.id"
        ).fetchall()
    items = [
        {
            "id": r["id"],
            "giriama": r["giriama"],
            "english": r["english"],
            "category": r["category"],
            "source_type": r["source_type"],
            "created_by": r["author"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {"items": items, "pending_count": len(items)}


def _entry_for_admin(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
    row = conn.execute(f"{_SELECT} WHERE e.id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return row


def approve_entry(db: Database, admin: dict, entry_id: int) -> dict:
    with db.write() as conn:
        row = _entry_for_admin(conn, entry_id)
        if row["verification_status"] == "pending":  # already approved: nothing to do
            _record_history(conn, row, admin["id"])
            conn.execute(
                "UPDATE entries SET verification_status = 'unverified', declined_at = NULL,"
                f" declined_by = NULL, updated_at = {NOW} WHERE id = ?",
                (entry_id,),
            )
            row = _entry_for_admin(conn, entry_id)
        return _public(row, admin)


def decline_entry(db: Database, admin: dict, entry_id: int) -> dict:
    with db.write() as conn:
        row = _entry_for_admin(conn, entry_id)
        if row["verification_status"] != "pending":
            raise HTTPException(status_code=409, detail="entry is already approved")
        if row["declined_at"] is None:  # already declined: nothing to do
            conn.execute(
                f"UPDATE entries SET declined_at = {NOW}, declined_by = ? WHERE id = ?",
                (admin["id"], entry_id),
            )
            row = _entry_for_admin(conn, entry_id)
        return _public(row, admin)


# ---- categories and the "gap" suggestion -------------------------------------------------------
def category_counts(db: Database, user: dict) -> list[dict]:
    with db.read() as conn:
        rows = conn.execute(
            f"SELECT e.category, count(*) AS n FROM entries e WHERE {VISIBLE}"
            " AND e.declined_at IS NULL GROUP BY e.category",
            _scope(user),
        ).fetchall()
    counts = {r["category"]: r["n"] for r in rows}
    return [
        {"id": cid, "label": CATEGORY_LABELS[cid], "count": counts.get(cid, 0)}
        for cid in CATEGORY_IDS
    ]


def gap_category(db: Database, user: dict) -> dict:
    """The group with the fewest entries; ties go to the order of CATEGORY_IDS."""
    return min(category_counts(db, user), key=lambda c: c["count"])
