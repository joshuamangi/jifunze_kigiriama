"""Import a hand-checked grammar review file. Run: make import-grammar FILE=path.json

Rows not marked "hand_checked": true are refused (use --allow-unchecked only to look at a draft).
See docs/grammar-review.example.json for the format. Nothing is ever generated here.
"""

import argparse
import sys

from app.config import Settings
from app.db import Database
from app.services.grammar import GrammarFileError, import_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Import grammar rules from a review file")
    parser.add_argument("file")
    parser.add_argument("--allow-unchecked", action="store_true")
    args = parser.parse_args()
    db = Database(Settings.from_env().database_path, readers=1)
    try:
        counts = import_file(db, args.file, args.allow_unchecked)
    except GrammarFileError as exc:
        print("nothing imported:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print("imported:", ", ".join(f"{n} {table}" for table, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
