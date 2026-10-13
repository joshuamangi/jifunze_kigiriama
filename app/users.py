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
