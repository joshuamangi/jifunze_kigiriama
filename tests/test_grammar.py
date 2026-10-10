import json

import pytest

from app.services.grammar import GrammarFileError, import_data, import_file, validate

# Abstract labels only: these tests must not contain any Kigiriama.
GOOD = {
    "label": "example class A",
    "rule": {"note": "test rule"},
    "source_page": "test source, p. 1",
    "confidence": "high",
    "hand_checked": True,
}


def rows(db, table):
    sql = f"SELECT * FROM {table} ORDER BY id"  # noqa: S608 - table names are fixed in this file
    with db.read() as conn:
        return [dict(r) for r in conn.execute(sql)]


def test_the_shipped_example_file_is_valid_and_imports_nothing(db):
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "docs/grammar-review.example.json"
    assert import_file(db, example) == {"noun_classes": 0, "verb_paradigms": 0}
    assert rows(db, "noun_classes") == [] and rows(db, "verb_paradigms") == []
    data = json.loads(example.read_text())
    assert data["noun_classes"] == [] and data["verb_paradigms"] == []
    assert data["_example_row"]["hand_checked"] is False  # copying it untouched is refused


def test_a_checked_row_is_imported_and_a_rerun_updates_instead_of_duplicating(db):
    data = {"noun_classes": [GOOD], "verb_paradigms": [{**GOOD, "label": "example paradigm"}]}
    assert import_data(db, data) == {"noun_classes": 1, "verb_paradigms": 1}
    changed = {"noun_classes": [{**GOOD, "confidence": "medium", "rule": {"note": "edited"}}]}
    import_data(db, changed)
    stored = rows(db, "noun_classes")
    assert len(stored) == 1 and stored[0]["confidence"] == "medium"
    assert json.loads(stored[0]["rule_json"]) == {"note": "edited"}
    assert stored[0]["hand_checked"] == 1 and stored[0]["source_page"] == "test source, p. 1"


def test_a_row_not_marked_hand_checked_is_refused_and_nothing_is_imported(db):
    data = {"noun_classes": [GOOD, {**GOOD, "label": "draft", "hand_checked": False}]}
    with pytest.raises(GrammarFileError, match="hand_checked"):
        import_data(db, data)
    assert rows(db, "noun_classes") == []  # all or nothing


def test_unchecked_rows_can_be_loaded_for_review_only_when_explicitly_allowed(db):
    import_data(db, {"noun_classes": [{**GOOD, "hand_checked": False}]}, allow_unchecked=True)
    assert rows(db, "noun_classes")[0]["hand_checked"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "label": ""},
        {**GOOD, "rule": "text"},
        {**GOOD, "source_page": ""},
        {**GOOD, "confidence": "certain"},
        {**GOOD, "hand_checked": "yes"},
        {**GOOD, "surprise": 1},
    ],
)
def test_malformed_rows_are_rejected(bad):
    with pytest.raises(GrammarFileError):
        validate({"noun_classes": [bad]})


def test_unknown_top_level_keys_and_bad_json_are_rejected(db, tmp_path):
    with pytest.raises(GrammarFileError, match="unknown top-level"):
        validate({"noun_class": []})
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(GrammarFileError, match="not valid JSON"):
        import_file(db, broken)
    with pytest.raises(GrammarFileError):
        validate([])
