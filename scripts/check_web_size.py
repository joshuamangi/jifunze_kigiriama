"""Fail if the front end outgrows its size budget (run by `make check-web-size` and CI).

The PWA has no build step, so what is in web/ is exactly what a phone downloads. The limits sit
a little above today's sizes: a jump means something large was added by accident.
"""

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
KB = 1024
# (label, file suffixes, limit in bytes); suffix None means every file.
BUDGETS = [
    ("JavaScript", {".js"}, 100 * KB),
    ("CSS", {".css"}, 40 * KB),
    ("HTML", {".html"}, 10 * KB),
    ("all of web/", None, 350 * KB),
]


def main() -> int:
    files = [p for p in WEB.rglob("*") if p.is_file()]
    failed = False
    for label, suffixes, limit in BUDGETS:
        total = sum(p.stat().st_size for p in files if suffixes is None or p.suffix in suffixes)
        over = total > limit
        failed = failed or over
        print(f"{'FAIL' if over else 'ok  '} {label}: {total / KB:.1f} KB of {limit / KB:.0f} KB")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
