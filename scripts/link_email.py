"""Attach a Cloudflare Access email (and optionally a role) to an existing account.

Run via `make link-email NAME=joshua EMAIL=you@example.com ROLE=admin`. This is how the owner's
existing account is matched to the owner's email, and how someone is made an admin. Other people
need nothing: their account is created the first time they pass Cloudflare Access.
"""

import argparse
import sys

from app.config import Settings
from app.db import Database
from app.users import ROLES, UserError, link_access_email


def main() -> int:
    parser = argparse.ArgumentParser(description="Link a Cloudflare Access email to an account")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=ROLES)
    args = parser.parse_args()

    settings = Settings.from_env()
    db = Database(settings.database_path, readers=1)
    try:
        user_id = link_access_email(db, args.username, args.email.strip(), args.role)
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"linked {args.email} to '{args.username}' (id {user_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
