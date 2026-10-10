"""Import grammar rules from a hand-prepared review file. Nothing is generated here.

The rules (noun classes, verb paradigms) come from Taylor's front matter and must be transcribed
and checked by a person. The importer only validates and stores what the file says, and refuses
any row not marked hand_checked, so unchecked OCR output cannot reach the database.
"""

import json
from pathlib import Path

from app.db import Database

TABLES = ("noun_classes", "verb_paradigms")
ROW_KEYS = {"label", "rule", "source_page", "confidence", "hand_checked"}
CONFIDENCE = {"low", "medium", "high"}


class GrammarFileError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def validate(data: object, allow_unchecked: bool = False) -> dict[str, list[dict]]:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise GrammarFileError(["the file must be a JSON object"])
    unknown = [k for k in data if k not in TABLES and not k.startswith("_")]
    if unknown:
        problems.append(f"unknown top-level key(s): {', '.join(unknown)}")
    rows: dict[str, list[dict]] = {}
    for table in TABLES:
        rows[table] = []
        for index, row in enumerate(data.get(table, []) or [], start=1):
            where = f"{table}[{index}]"
            if not isinstance(row, dict):
                problems.append(f"{where}: must be an object")
                continue
            extra = sorted(set(row) - ROW_KEYS)
            if extra:
                problems.append(f"{where}: unknown field(s) {', '.join(extra)}")
            label = row.get("label")
            if not isinstance(label, str) or not label.strip() or len(label) > 200:
                problems.append(f"{where}: label must be a non-empty string")
            if not isinstance(row.get("rule"), dict):
                problems.append(f"{where}: rule must be a JSON object")
            page = row.get("source_page")
            if not isinstance(page, str) or not page.strip():
                problems.append(f"{where}: source_page is required (the page it came from)")
            if row.get("confidence") not in CONFIDENCE:
                problems.append(f"{where}: confidence must be one of {sorted(CONFIDENCE)}")
            if row.get("hand_checked") is not True and not allow_unchecked:
                problems.append(f"{where}: not marked hand_checked, so it is not imported")
            rows[table].append(row)
    if problems:
        raise GrammarFileError(problems)
    return rows


def import_data(db: Database, data: object, allow_unchecked: bool = False) -> dict[str, int]:
    """All or nothing: every row is validated first, then written in one transaction."""
    rows = validate(data, allow_unchecked)
    counts = {}
    with db.write() as conn:
        for table in TABLES:
            written = 0
            for row in rows[table]:
                values = (
                    json.dumps(row["rule"], ensure_ascii=False, sort_keys=True),
                    row["source_page"].strip(),
                    row["confidence"],
                    1 if row.get("hand_checked") is True else 0,
                )
                existing = conn.execute(
                    f"SELECT id FROM {table} WHERE label = ?", (row["label"].strip(),)
                ).fetchone()
                if existing:
                    conn.execute(
                        f"UPDATE {table} SET rule_json = ?, source_page = ?, confidence = ?,"
                        f" hand_checked = ? WHERE id = ?",
                        (*values, existing["id"]),
                    )
                else:
                    conn.execute(
                        f"INSERT INTO {table} (label, rule_json, source_page, confidence,"
                        f" hand_checked) VALUES (?, ?, ?, ?, ?)",
                        (row["label"].strip(), *values),
                    )
                written += 1
            counts[table] = written
    return counts


def import_file(db: Database, path: str | Path, allow_unchecked: bool = False) -> dict[str, int]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GrammarFileError([f"not valid JSON: {exc}"]) from exc
    return import_data(db, data, allow_unchecked)
