"""Set a new password for an existing account. Run via `make reset-password NAME=joshua`.

Run on the machine that holds the database; there is no web route for this. The password is typed
at the terminal prompt, so it never appears in shell history or argv. The account is signed out
everywhere.
"""

import argparse
import getpass
import sys

from app.auth.hashing import PasswordService
from app.config import Settings
from app.db import Database
from app.users import UserError, reset_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a Jifunze Kigiriama password")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat new password: "):
        print("passwords do not match", file=sys.stderr)
        return 1

    settings = Settings.from_env()
    db = Database(settings.database_path, readers=1)
    try:
        user_id = reset_password(
            db,
            PasswordService(settings),
            args.username,
            password,
            min_length=settings.password_min_length,
        )
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"password reset for '{args.username}' (id {user_id}); signed out everywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
