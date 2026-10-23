"""Account creation. Only an admin at the command line can create users; there is no sign-up."""

import re
import sqlite3

from app import audit
from app.auth.hashing import PasswordService
from app.db import Database

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
MIN_PASSWORD_LENGTH = 12  # the default; Settings.password_min_length (PASSWORD_MIN_LENGTH) wins
MAX_PASSWORD_LENGTH = 1024
ROLES = ("admin", "member")
# Stored for accounts made by Cloudflare Access. It is not an argon2 hash, so PasswordService
# .verify() rejects every password against it until the person sets one.
UNUSABLE_HASH = "!"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserError(ValueError):
    pass


def create_user(
    db: Database,
    passwords: PasswordService,
    username: str,
    password: str,
    role: str,
    min_length: int = MIN_PASSWORD_LENGTH,
) -> int:
    if not USERNAME_RE.match(username):
        raise UserError("username must be 3-32 characters: letters, digits, '.', '_' or '-'")
    if role not in ROLES:
        raise UserError("role must be 'admin' or 'member'")
    if not min_length <= len(password) <= MAX_PASSWORD_LENGTH:
        raise UserError(f"password must be {min_length} to {MAX_PASSWORD_LENGTH} characters")
    password_hash = passwords.hash(password)
    try:
        with db.write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise UserError("that username is already taken") from None
    # Accounts are made at the command line, so there is no request or signed-in actor to name.
    audit.record(db, "user.create", target=f"user:{user_id}", detail=f"{role} {username}")
    return user_id


def reset_password(
    db: Database,
    passwords: PasswordService,
    username: str,
    password: str,
    min_length: int = MIN_PASSWORD_LENGTH,
) -> int:
    """Set a new password for an existing account and sign it out everywhere.

    Command line only, like create_user: there is no route for it. Old sessions are deleted so
    a stolen or forgotten login does not survive the reset. Returns the user id.
    """
    if not min_length <= len(password) <= MAX_PASSWORD_LENGTH:
        raise UserError(f"password must be {min_length} to {MAX_PASSWORD_LENGTH} characters")
    password_hash = passwords.hash(password)
    with db.write() as conn:
        row = conn.execute(
            "SELECT id, username FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if row is None:
            raise UserError("no account with that username")
        user_id, stored_name = row[0], row[1]
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    audit.record(db, "user.password_reset", target=f"user:{user_id}", detail=stored_name)
    return user_id


def _username_from_email(email: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "", email.split("@", 1)[0])[:28]
    return base.ljust(3, "_")


def find_by_access_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, role FROM users WHERE access_email = ? COLLATE NOCASE", (email,)
    ).fetchone()


def create_access_user(db: Database, email: str) -> dict:
    """Make a member account for an email Cloudflare Access has verified, with no usable password.

    The username comes from the part before the @, with a number added if it is taken. Safe if two
    first requests arrive together: the loser of the race gets the winner's account.
    """
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise UserError("not a valid email address")
    base = _username_from_email(email)
    with db.write() as conn:
        existing = find_by_access_email(conn, email)
        if existing is not None:
            return {**dict(existing), "new": False}
        for n in range(1, 100):
            username = base if n == 1 else f"{base[:28]}{n}"
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, access_email, password_hash, role)"
                    " VALUES (?, ?, ?, 'member')",
                    (username, email, UNUSABLE_HASH),
                )
            except sqlite3.IntegrityError:
                continue  # the username is taken; try the next
            user = {"id": cur.lastrowid, "username": username, "role": "member", "new": True}
            break
        else:
            raise UserError("could not find a free username")
    audit.record(db, "user.create_access", target=f"user:{user['id']}", detail=username)
    return user


def set_own_password(
    db: Database,
    passwords: PasswordService,
    user_id: int,
    password: str,
    min_length: int = MIN_PASSWORD_LENGTH,
) -> None:
    if not min_length <= len(password) <= MAX_PASSWORD_LENGTH:
        raise UserError(f"password must be {min_length} to {MAX_PASSWORD_LENGTH} characters")
    password_hash = passwords.hash(password)
    with db.write() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


def link_access_email(db: Database, username: str, email: str, role: str | None = None) -> int:
    """Attach a verified Access email (and optionally a role) to an existing account. CLI only."""
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise UserError("not a valid email address")
    if role is not None and role not in ROLES:
        raise UserError("role must be 'admin' or 'member'")
    try:
        with db.write() as conn:
            row = conn.execute(
                "SELECT id, username FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            if row is None:
                raise UserError("no account with that username")
            conn.execute("UPDATE users SET access_email = ? WHERE id = ?", (email, row["id"]))
            if role is not None:
                conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, row["id"]))
    except sqlite3.IntegrityError:
        raise UserError("another account already uses that email") from None
    audit.record(
        db, "user.link_email", target=f"user:{row['id']}", detail=f"{row['username']} {role or ''}"
    )
    return row["id"]
