import pytest
from fastapi.testclient import TestClient

from tests.helpers import GUARD_HEADERS

# Only verified words (CLAUDE.md): mwenga=one, hiri=two, hahu=three, kumi na hahu=thirteen.
ONE = {"giriama": "mwenga", "english": "one", "category": "numbers", "source_type": "own"}
TWO = {"giriama": "hiri", "english": "two", "category": "numbers", "source_type": "dictionary"}
THREE = {"giriama": "hahu", "english": "three", "category": "numbers", "source_type": "own"}
THIRTEEN = {
    "giriama": "kumi na hahu",
    "english": "thirteen",
    "category": "numbers",
    "source_type": "own",
}


@pytest.fixture
def amina(login_as):
    return login_as("amina")


@pytest.fixture
def baraka(login_as):
    return login_as("baraka")


@pytest.fixture
def boss(login_as):
    return login_as("boss", "admin")


def add(client, body=ONE):
    response = client.post("/api/entries", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def ids(response):
    return [item["id"] for item in response.json()["items"]]


# ---- create ---------------------------------------------------------------------------------
def test_member_creates_pending_and_admin_creates_unverified(amina, boss):
    mine = add(amina)
    assert mine["verification_status"] == "pending"
    assert mine["mine"] is True
    assert "created_by" not in mine  # members never see author names
    theirs = add(boss, TWO)
    assert theirs["verification_status"] == "unverified"
    assert theirs["created_by"] == "boss"


def test_input_validation(amina):
    bad_bodies = [
        {**ONE, "category": "weather"},
        {**ONE, "source_type": "verse"},  # the schema value is 'scripture'
        {**ONE, "english": "   "},
        {**ONE, "giriama": ""},
        {**ONE, "english": "x" * 1001},
        {**ONE, "verification_status": "native_verified"},  # unknown field
        {"giriama": "mwenga"},
    ]
    for body in bad_bodies:
        assert amina.post("/api/entries", json=body).status_code == 422, body


def test_text_is_trimmed(amina):
    entry = add(amina, {**ONE, "giriama": "  mwenga  ", "english": " one "})
    assert (entry["giriama"], entry["english"]) == ("mwenga", "one")


def test_markup_comes_back_as_plain_text_in_json(amina):
    payload = "<script>alert(1)</script>"
    entry = add(amina, {**ONE, "english": payload})
    response = amina.get(f"/api/entries/{entry['id']}")
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["english"] == payload


# ---- visibility -----------------------------------------------------------------------------
def test_member_cannot_see_another_members_pending_entry_anywhere(amina, baraka, boss):
    entry = add(amina)
    eid = entry["id"]
    assert baraka.get(f"/api/entries/{eid}").status_code == 404
    assert baraka.get(f"/api/entries/{eid}/history").status_code == 404
    assert baraka.patch(f"/api/entries/{eid}", json={"english": "uno"}).status_code == 404
    assert ids(baraka.get("/api/entries")) == []
    assert ids(baraka.get("/api/entries", params={"q": "one"})) == []
    assert ids(baraka.get("/api/entries", params={"category": "numbers"})) == []
    assert sum(c["count"] for c in baraka.get("/api/categories").json()) == 0
    # the author and an admin do see it
    assert ids(amina.get("/api/entries")) == [eid]
    assert ids(boss.get("/api/entries")) == [eid]
    assert boss.get(f"/api/entries/{eid}").status_code == 200


def test_approved_entry_is_visible_to_other_members(amina, baraka, boss):
    eid = add(amina)["id"]
    boss.post(f"/api/review/{eid}/approve")
    seen = baraka.get(f"/api/entries/{eid}")
    assert seen.status_code == 200
    assert seen.json()["mine"] is False
    assert "created_by" not in seen.json()


def test_unknown_entry_is_404(amina):
    assert amina.get("/api/entries/9999").status_code == 404


# ---- edit and history -----------------------------------------------------------------------
def test_edit_in_place_records_history_with_old_values(amina, boss):
    eid = add(amina)["id"]
    edited = amina.patch(f"/api/entries/{eid}", json={"english": "one (1)"})
    assert edited.status_code == 200
    assert edited.json()["english"] == "one (1)"
    history = amina.get(f"/api/entries/{eid}/history").json()
    assert len(history) == 1
    assert history[0]["old"]["english"] == "one"
    assert history[0]["old"]["giriama"] == "mwenga"
    assert history[0]["changed_by_you"] is True
    assert "changed_by" not in history[0]
    admin_view = boss.get(f"/api/entries/{eid}/history").json()
    assert admin_view[0]["changed_by"] == "amina"


def test_every_edit_adds_a_history_row_newest_first(amina):
    eid = add(amina)["id"]
    amina.patch(f"/api/entries/{eid}", json={"english": "first"})
    amina.patch(f"/api/entries/{eid}", json={"english": "second"})
    history = amina.get(f"/api/entries/{eid}/history").json()
    assert [h["old"]["english"] for h in history] == ["first", "one"]


def test_no_op_patch_writes_no_history(amina):
    eid = add(amina)["id"]
    same = amina.patch(f"/api/entries/{eid}", json={"english": "  one  ", "category": "numbers"})
    assert same.status_code == 200
    assert amina.get(f"/api/entries/{eid}/history").json() == []


def test_patch_rejects_nulls_and_unknown_fields(amina):
    eid = add(amina)["id"]
    assert amina.patch(f"/api/entries/{eid}", json={"english": None}).status_code == 422
    assert amina.patch(f"/api/entries/{eid}", json={"created_by": 1}).status_code == 422
    assert amina.patch(f"/api/entries/{eid}", json={"category": "weather"}).status_code == 422


def test_member_cannot_edit_someone_elses_visible_entry(amina, baraka, boss):
    eid = add(amina)["id"]
    boss.post(f"/api/review/{eid}/approve")
    assert baraka.patch(f"/api/entries/{eid}", json={"english": "uno"}).status_code == 403
    assert baraka.get(f"/api/entries/{eid}/history").status_code == 403


def test_member_cannot_set_verification_status(amina):
    eid = add(amina)["id"]
    response = amina.patch(f"/api/entries/{eid}", json={"verification_status": "unverified"})
    assert response.status_code == 403


def test_member_cannot_edit_a_native_verified_entry_but_admin_can(amina, boss):
    eid = add(amina)["id"]
    set_status = boss.patch(f"/api/entries/{eid}", json={"verification_status": "native_verified"})
    assert set_status.status_code == 200
    assert amina.patch(f"/api/entries/{eid}", json={"english": "uno"}).status_code == 403
    admin_edit = boss.patch(f"/api/entries/{eid}", json={"english": "one (counted)"})
    assert admin_edit.status_code == 200
    assert admin_edit.json()["verification_status"] == "native_verified"


def test_member_edit_of_an_approved_entry_goes_back_to_review(amina, baraka, boss):
    eid = add(amina)["id"]
    boss.post(f"/api/review/{eid}/approve")
    assert ids(baraka.get("/api/entries")) == [eid]

    edited = amina.patch(f"/api/entries/{eid}", json={"english": "one (1)"}).json()
    assert edited["verification_status"] == "pending"
    assert ids(baraka.get("/api/entries")) == []  # hidden until re-approved
    assert [i["id"] for i in boss.get("/api/review").json()["items"]] == [eid]
    olds = [
        h["old"]["verification_status"] for h in amina.get(f"/api/entries/{eid}/history").json()
    ]
    assert olds == ["unverified", "pending"]


def test_english_edit_clears_embedded_at_other_edits_do_not(amina, db):
    eid = add(amina)["id"]
    stamp = "UPDATE entries SET embedded_at = '2026-01-01T00:00:00.000Z' WHERE id = ?"
    with db.write() as conn:
        conn.execute(stamp, (eid,))
    amina.patch(f"/api/entries/{eid}", json={"category": "family"})
    with db.read() as conn:
        assert conn.execute("SELECT embedded_at FROM entries").fetchone()[0] is not None
    amina.patch(f"/api/entries/{eid}", json={"english": "one (1)"})
    with db.read() as conn:
        assert conn.execute("SELECT embedded_at FROM entries").fetchone()[0] is None


# ---- list, search, paging -------------------------------------------------------------------
def test_category_filter_and_paging(boss):
    for body in (ONE, TWO, THREE):
        add(boss, body)
    add(boss, {**ONE, "category": "family", "english": "uno-family"})
    numbers = boss.get("/api/entries", params={"category": "numbers"}).json()
    assert numbers["total"] == 3
    page = boss.get("/api/entries", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    rest = boss.get("/api/entries", params={"limit": 2, "offset": 2}).json()
    assert len(rest["items"]) == 2
    assert not {i["id"] for i in page["items"]} & {i["id"] for i in rest["items"]}
    assert boss.get("/api/entries", params={"limit": 101}).status_code == 422
    assert boss.get("/api/entries", params={"category": "weather"}).status_code == 422


def test_keyword_search_matches_english_giriama_and_prefixes(boss):
    add(boss, THIRTEEN)
    add(boss, TWO)
    assert len(boss.get("/api/entries", params={"q": "thirteen"}).json()["items"]) == 1
    assert len(boss.get("/api/entries", params={"q": "thir"}).json()["items"]) == 1
    assert len(boss.get("/api/entries", params={"q": "kumi hahu"}).json()["items"]) == 1
    assert boss.get("/api/entries", params={"q": "hiri"}).json()["total"] == 1
    assert boss.get("/api/entries", params={"q": "zzz"}).json()["total"] == 0


@pytest.mark.parametrize(
    "q",
    ['"', "a OR", "NEAR(", "*", "one*", "'; DROP TABLE entries;--", "(", "one AND", "-one", "^"],
)
def test_search_input_never_breaks_the_query(boss, q):
    add(boss)
    response = boss.get("/api/entries", params={"q": q})
    assert response.status_code == 200
    with_table = boss.get("/api/entries")
    assert with_table.json()["total"] == 1  # the table is still there


# ---- categories and gap ---------------------------------------------------------------------
def test_gap_is_the_group_with_fewest_entries_ties_by_list_order(boss):
    assert boss.get("/api/suggestions/gap").json()["id"] == "greetings"
    for body, category in ((ONE, "greetings"), (TWO, "family"), (THREE, "numbers")):
        add(boss, {**body, "category": category})
    # proverbs and food are tied at 0 -> first in list order
    assert boss.get("/api/suggestions/gap").json() == {
        "id": "proverbs",
        "label": "Proverbs",
        "count": 0,
    }
    add(boss, {**ONE, "category": "proverbs", "english": "p"})
    assert boss.get("/api/suggestions/gap").json()["id"] == "food"


def test_category_counts_follow_visibility(amina, baraka, boss):
    eid = add(amina)["id"]
    count = lambda c: {x["id"]: x["count"] for x in c.get("/api/categories").json()}["numbers"]  # noqa: E731
    assert (count(amina), count(baraka), count(boss)) == (1, 0, 1)
    boss.post(f"/api/review/{eid}/approve")
    assert count(baraka) == 1


# ---- sessions -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/entries"),
        ("POST", "/api/entries"),
        ("GET", "/api/entries/1"),
        ("PATCH", "/api/entries/1"),
        ("GET", "/api/entries/1/history"),
        ("GET", "/api/categories"),
        ("GET", "/api/suggestions/gap"),
    ],
)
def test_anonymous_requests_are_rejected(app, method, path):
    anon = TestClient(app, headers=GUARD_HEADERS)
    assert anon.request(method, path, json={}).status_code == 401
