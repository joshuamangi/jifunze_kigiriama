"""Create an account. Run via `make create-user NAME=joshua ROLE=admin`.

The password is typed at the terminal prompt, so it never appears in shell history or argv.
"""

import argparse
import getpass
import sys

from app.auth.hashing import PasswordService
from app.config import Settings
from app.db import Database
from app.users import ROLES, UserError, create_user


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Jifunze Kigiriama account")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=ROLES, default="member")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("passwords do not match", file=sys.stderr)
        return 1

    settings = Settings.from_env()
    db = Database(settings.database_path, readers=1)
    try:
        user_id = create_user(
            db,
            PasswordService(settings),
            args.username,
            password,
            args.role,
            min_length=settings.password_min_length,
        )
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"created {args.role} '{args.username}' (id {user_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
