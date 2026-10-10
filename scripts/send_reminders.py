"""Send the study reminder emails that are due. Run: make send-reminders

Meant for a systemd timer every 15 minutes (Stage 8); safe to run any number of times a day: each
user gets at most one email per local day. Exits 1 if any send failed, so the timer's failure
handling can notice.

  python scripts/send_reminders.py --backend=console   # print the emails (the default locally)
  python scripts/send_reminders.py --backend=smtp      # SMTP_* settings from the environment
  python scripts/send_reminders.py --dry-run           # show who would get one
"""

import argparse
import os
import sys

from app.config import Settings
from app.db import Database
from app.services.reminders import ConsoleBackend, SmtpBackend, SmtpConfig, run_reminders


def main() -> int:
    parser = argparse.ArgumentParser(description="Send due study reminders")
    parser.add_argument(
        "--backend",
        choices=["console", "smtp"],
        default=os.environ.get("REMINDER_BACKEND", "console"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    backend = ConsoleBackend() if args.backend == "console" else SmtpBackend(SmtpConfig.from_env())
    db = Database(settings.database_path, readers=1)
    try:
        result = run_reminders(
            db,
            settings,
            backend,
            dry_run=args.dry_run,
            base_url=os.environ.get("APP_BASE_URL") or None,
        )
    finally:
        db.close()
    skipped = ", ".join(f"{n} {why}" for why, n in result["skipped"].items()) or "none"
    print(f"reminders: sent {result['sent']}, failed {result['failed']}, skipped: {skipped}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
