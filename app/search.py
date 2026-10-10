"""Keyword (FTS5) and semantic (sqlite-vec) search with the same visibility rules as listing.

Both modes produce a ranked list of candidate entry ids; candidates are then filtered by what the
caller may see. The vector index cannot filter by visibility itself, so candidates are over-fetched
and the fetch size doubled until enough visible rows are found or the index is exhausted. That is
cheap at this scale (low thousands of rows) and never shows an entry the caller cannot see.

Only English text is embedded. The semantic query is expected to be English; entries.giriama is
never read by any embedding code.
"""

import sqlite3
from typing import Literal

from app.db import Database
from app.embeddings.base import Embedder
from app.embeddings.worker import pack
from app.entries import _SELECT, VISIBLE, _public, _scope, fts_query

Mode = Literal["keyword", "semantic"]
MAX_CANDIDATES = 200
OVERFETCH = 4


def _keyword_candidates(conn: sqlite3.Connection, match: str, n: int) -> list[tuple[int, float]]:
    rows = conn.execute(
        "SELECT rowid, bm25(entries_fts) AS r FROM entries_fts WHERE entries_fts MATCH ?"
        " ORDER BY r LIMIT ?",
        (match, n),
    ).fetchall()
    return [(row["rowid"], -row["r"]) for row in rows]  # bm25 is lower-is-better; flip it


def _semantic_candidates(
    conn: sqlite3.Connection, query_vec: bytes, n: int
) -> list[tuple[int, float]]:
    rows = conn.execute(
        "SELECT entry_id, distance FROM entry_vec WHERE embedding MATCH ? AND k = ?",
        (query_vec, n),
    ).fetchall()
    # Vectors are unit length, so cosine similarity = 1 - d^2 / 2 for L2 distance d.
    return [(row["entry_id"], 1.0 - (row["distance"] ** 2) / 2.0) for row in rows]


def _visible(
    conn: sqlite3.Connection, user: dict, ranked: list[tuple[int, float]], limit: int
) -> list[dict]:
    if not ranked:
        return []
    params = {**_scope(user), **{f"i{n}": entry_id for n, (entry_id, _) in enumerate(ranked)}}
    marks = ",".join(f":i{n}" for n in range(len(ranked)))
    rows = conn.execute(f"{_SELECT} WHERE e.id IN ({marks}) AND {VISIBLE}", params).fetchall()
    by_id = {row["id"]: row for row in rows}
    out = []
    for entry_id, score in ranked:  # keep the ranking order
        row = by_id.get(entry_id)
        if row is None:
            continue
        item = _public(row, user)
        item["score"] = round(score, 4)
        out.append(item)
        if len(out) == limit:
            break
    return out


def _search(conn: sqlite3.Connection, user: dict, fetch, limit: int) -> list[dict]:
    n = min(limit * OVERFETCH, MAX_CANDIDATES)
    while True:
        candidates = fetch(conn, n)
        items = _visible(conn, user, candidates, limit)
        exhausted = len(candidates) < n or n >= MAX_CANDIDATES
        if len(items) >= limit or exhausted:
            return items
        n = min(n * 2, MAX_CANDIDATES)


def not_yet_indexed(conn: sqlite3.Connection, user: dict) -> int:
    """Visible entries that do not have a vector yet, so an empty result is not misread."""
    return conn.execute(
        f"SELECT count(*) FROM entries e WHERE {VISIBLE} AND e.embedded_at IS NULL", _scope(user)
    ).fetchone()[0]


def search_entries(
    db: Database, embedder: Embedder, user: dict, q: str, mode: Mode, limit: int
) -> dict:
    if mode == "keyword":
        match = fts_query(q)
        if not match:
            return {"mode": mode, "items": [], "not_yet_indexed": None}
        with db.read() as conn:
            items = _search(conn, user, lambda c, n: _keyword_candidates(c, match, n), limit)
        return {"mode": mode, "items": items, "not_yet_indexed": None}

    query_vec = pack(embedder.embed([q.strip()])[0])  # embed outside any database connection
    with db.read() as conn:
        items = _search(conn, user, lambda c, n: _semantic_candidates(c, query_vec, n), limit)
        pending = not_yet_indexed(conn, user)
    return {"mode": mode, "items": items, "not_yet_indexed": pending}
