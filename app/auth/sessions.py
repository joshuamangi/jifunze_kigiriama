"""Server-side sessions. The cookie holds a random token; only its SHA-256 hash is stored."""

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from app.config import Settings

COOKIE_NAME = "session"
# last_seen_at is refreshed at most this often, to avoid a database write on every request.
TOUCH_INTERVAL = timedelta(minutes=1)
_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now() -> datetime:
    return datetime.now(UTC)


def _fmt(moment: datetime) -> str:
    # Millisecond precision, same shape as the schema's strftime defaults, so text compares sort.
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _parse(text: str) -> datetime:
    return datetime.strptime(text, _FMT).replace(tzinfo=UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, settings: Settings, user_id: int, now=None) -> str:
    """Create a session inside the caller's write transaction; return the raw token."""
    now = now or _now()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_fmt(now),))
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(seconds=settings.session_max_age_seconds)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, last_seen_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (hash_token(token), user_id, _fmt(now), _fmt(now), _fmt(expires)),
    )
    return token


def lookup_session(
    conn: sqlite3.Connection, settings: Settings, token: str, now=None
) -> sqlite3.Row | None:
    """Return the user row for a valid token, else None. Read-only; see should_touch."""
    now = now or _now()
    row = conn.execute(
        "SELECT u.id, u.username, u.role, s.token_hash, s.last_seen_at, s.expires_at"
        " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (hash_token(token),),
    ).fetchone()
    if row is None:
        return None
    if _parse(row["expires_at"]) <= now:
        return None
    if now - _parse(row["last_seen_at"]) > timedelta(seconds=settings.session_idle_seconds):
        return None
    return row


def should_touch(row: sqlite3.Row, now=None) -> bool:
    now = now or _now()
    return now - _parse(row["last_seen_at"]) >= TOUCH_INTERVAL


def touch_session(conn: sqlite3.Connection, token_hash: str, now=None) -> None:
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
        (_fmt(now or _now()), token_hash),
    )


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
