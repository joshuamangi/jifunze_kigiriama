"""Email the owner that a systemd unit failed. Run by jifunze-failure@.service.

  python scripts/notify_failure.py jifunze-backup.service

Needs ALERT_EMAIL; sends with the same SMTP_* settings as the reminders (ALERT_BACKEND=console
prints instead). The email carries the last lines of the unit's log, which can mention usernames,
so it only ever goes to the owner's own address.
"""

import os
import re
import socket
import subprocess
import sys

from app.services.reminders import Backend, ConsoleBackend, SmtpBackend, SmtpConfig

UNIT = re.compile(r"^jifunze[A-Za-z0-9:_.@-]*\.(service|timer)$")
LOG_LINES = 25


def compose(unit: str, host: str, log_tail: str) -> tuple[str, str]:
    subject = f"[jifunze] {unit} failed on {host}"
    body = (
        f"The systemd unit {unit} failed on {host}.\n\n"
        f"Last {LOG_LINES} log lines:\n\n{log_tail or '(no log lines available)'}\n\n"
        f"On the Pi: journalctl -u {unit} -n 100 --no-pager\n"
    )
    return subject, body


def journal_tail(unit: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - the unit name is validated by UNIT
            ["journalctl", "-u", unit, "-n", str(LOG_LINES), "--no-pager", "-o", "cat"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def notify(unit: str, to: str, backend: Backend, host: str, log_tail: str) -> None:
    subject, body = compose(unit, host, log_tail)
    backend.send(to, subject, body)


def main() -> int:
    if len(sys.argv) != 2 or not UNIT.match(sys.argv[1]):
        print("usage: notify_failure.py <jifunze unit name>", file=sys.stderr)
        return 2
    unit = sys.argv[1]
    to = os.environ.get("ALERT_EMAIL", "").strip()
    if not to:
        print("ALERT_EMAIL is not set: cannot send the failure alert", file=sys.stderr)
        return 1
    kind = os.environ.get("ALERT_BACKEND") or os.environ.get("REMINDER_BACKEND", "console")
    backend = SmtpBackend(SmtpConfig.from_env()) if kind == "smtp" else ConsoleBackend()
    notify(unit, to, backend, socket.gethostname(), journal_tail(unit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
