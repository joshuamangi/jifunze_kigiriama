"""Study reminder emails. Runs as its own process (scripts/send_reminders.py), never in the web app.

A reminder is sent at most once per local day per user: the day is claimed in the database before
sending and given back if sending fails, so overlapping runs cannot double-send and a failure is
retried on the next run. The email states real counts and contains no entry text.
"""

import os
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from app.config import Settings
from app.db import Database
from app.services import learn

LINES_PER_MINUTE = 2  # a card takes about 30 seconds


class Backend(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleBackend(Backend):
    """Prints the email instead of sending it (local use)."""

    def __init__(self, out=print) -> None:
        self._out = out

    def send(self, to: str, subject: str, body: str) -> None:
        self._out(f"--- email to {to}\nSubject: {subject}\n\n{body}\n---")


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str | None
    password: str | None
    sender: str
    starttls: bool

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "SmtpConfig":
        env = os.environ if env is None else env
        missing = [k for k in ("SMTP_HOST", "SMTP_FROM") if not env.get(k)]
        if missing:
            raise RuntimeError(f"SMTP backend needs {', '.join(missing)} in the environment")
        return cls(
            host=env["SMTP_HOST"],
            port=int(env.get("SMTP_PORT") or 587),
            user=env.get("SMTP_USER") or None,
            password=env.get("SMTP_PASSWORD") or None,
            sender=env["SMTP_FROM"],
            starttls=(env.get("SMTP_STARTTLS", "true").strip().lower() not in {"0", "false", "no"}),
        )


class SmtpBackend(Backend):
    def __init__(self, config: SmtpConfig) -> None:
        self._config = config

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self._config.sender, to, subject
        message.set_content(body)
        with smtplib.SMTP(self._config.host, self._config.port, timeout=30) as smtp:
            if self._config.starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self._config.user:
                smtp.login(self._config.user, self._config.password or "")
            smtp.send_message(message)


def compose(username: str, due: int, new: int, base_url: str | None) -> tuple[str, str]:
    total = due + new
    subject = f"Jifunze Kigiriama: {total} {'card' if total == 1 else 'cards'} to study today"
    minutes = max(1, round(total / LINES_PER_MINUTE))
    lines = [
        f"Hello {username},",
        "",
        f"Today you have {due} to review and {new} new, about {minutes} minutes.",
    ]
    if base_url:
        lines += ["", f"Open the app: {base_url}"]
    lines += ["", "To stop these emails, turn off the study reminder in Settings."]
    return subject, "\n".join(lines)


def run_reminders(
    db: Database,
    settings: Settings,
    backend: Backend,
    now: datetime | None = None,
    dry_run: bool = False,
    base_url: str | None = None,
    log=print,
) -> dict:
    """Send every reminder that is due. Returns counts: sent, skipped (by reason), failed."""
    zone = ZoneInfo(settings.app_timezone)
    local = now.astimezone(zone) if now else datetime.now(zone)
    today = local.date()
    result = {"sent": 0, "failed": 0, "skipped": {}}

    def skip(reason: str, who: str) -> None:
        result["skipped"][reason] = result["skipped"].get(reason, 0) + 1
        log(f"skip {who}: {reason}")

    with db.read() as conn:
        rows = conn.execute(
            "SELECT r.user_id, r.send_at, r.frequency, r.last_sent_on, u.username, u.email"
            " FROM reminders r JOIN users u ON u.id = r.user_id WHERE r.enabled = 1"
            " ORDER BY r.user_id"
        ).fetchall()

    for row in rows:
        who = f"user {row['user_id']}"
        if not row["email"]:
            skip("no email address", who)
        elif row["last_sent_on"] == today.isoformat():
            skip("already sent today", who)
        elif row["frequency"] == "weekdays" and today.weekday() >= 5:
            skip("weekend", who)
        elif local.strftime("%H:%M") < row["send_at"]:
            skip("not time yet", who)
        else:
            user = {"id": row["user_id"], "username": row["username"], "role": "member"}
            report = learn.summary(db, user, today, settings)
            due, new = report["due_today"], report["new_available"]
            if due + new == 0:
                skip("nothing to study", who)
                continue
            subject, body = compose(row["username"], due, new, base_url)
            if dry_run:
                log(f"dry run: would send to {who}: {subject}")
                continue
            if not _claim(db, row["user_id"], today.isoformat()):
                skip("already sent today", who)
                continue
            try:
                backend.send(row["email"], subject, body)
            except Exception as exc:  # any send failure: give the day back and retry next run
                _release(db, row["user_id"], row["last_sent_on"])
                result["failed"] += 1
                log(f"FAILED {who}: {type(exc).__name__}: {exc}")
            else:
                result["sent"] += 1
                log(f"sent {who}")
    return result


def _claim(db: Database, user_id: int, day: str) -> bool:
    with db.write() as conn:
        cur = conn.execute(
            "UPDATE reminders SET last_sent_on = ? WHERE user_id = ?"
            " AND (last_sent_on IS NULL OR last_sent_on != ?)",
            (day, user_id, day),
        )
        return cur.rowcount == 1


def _release(db: Database, user_id: int, previous: str | None) -> None:
    with db.write() as conn:
        conn.execute("UPDATE reminders SET last_sent_on = ? WHERE user_id = ?", (previous, user_id))
