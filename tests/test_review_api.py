import pytest
from fastapi.testclient import TestClient

from tests.helpers import GUARD_HEADERS
from tests.test_entries_api import ONE, THREE, TWO, add, ids  # noqa: F401


@pytest.fixture
def amina(login_as):
    return login_as("amina")


@pytest.fixture
def baraka(login_as):
    return login_as("baraka")


@pytest.fixture
def boss(login_as):
    return login_as("boss", "admin")


REVIEW_ROUTES = [
    ("GET", "/api/review"),
    ("POST", "/api/review/1/approve"),
    ("POST", "/api/review/1/decline"),
]


@pytest.mark.parametrize(("method", "path"), REVIEW_ROUTES)
def test_review_routes_are_admin_only(app, amina, method, path):
    assert amina.request(method, path).status_code == 403
    anon = TestClient(app, headers=GUARD_HEADERS)
    assert anon.request(method, path).status_code == 401


def test_members_cannot_approve_their_own_entry(amina):
    eid = add(amina)["id"]
    assert amina.post(f"/api/review/{eid}/approve").status_code == 403
    assert amina.get(f"/api/entries/{eid}").json()["verification_status"] == "pending"


def test_queue_shows_pending_with_source_and_author_oldest_first(amina, baraka, boss):
    first = add(amina, TWO)["id"]
    second = add(baraka, ONE)["id"]
    queue = boss.get("/api/review").json()
    assert queue["pending_count"] == 2
    assert [i["id"] for i in queue["items"]] == [first, second]
    assert queue["items"][0]["source_type"] == "dictionary"
    assert queue["items"][0]["created_by"] == "amina"


def test_queue_excludes_approved_declined_and_admin_entries(amina, boss):
    approved = add(amina, ONE)["id"]
    declined = add(amina, TWO)["id"]
    waiting = add(amina, THREE)["id"]
    add(boss, {**ONE, "english": "admin-made"})
    boss.post(f"/api/review/{approved}/approve")
    boss.post(f"/api/review/{declined}/decline")
    assert [i["id"] for i in boss.get("/api/review").json()["items"]] == [waiting]


def test_approve_makes_it_visible_and_twice_is_harmless(amina, baraka, boss):
    eid = add(amina)["id"]
    first = boss.post(f"/api/review/{eid}/approve")
    assert first.status_code == 200
    assert first.json()["verification_status"] == "unverified"
    stamp = first.json()["updated_at"]
    again = boss.post(f"/api/review/{eid}/approve")
    assert again.status_code == 200
    assert again.json()["updated_at"] == stamp
    assert len(boss.get(f"/api/entries/{eid}/history").json()) == 1  # not two
    assert ids(baraka.get("/api/entries")) == [eid]


def test_decline_hides_from_others_keeps_for_author_and_twice_is_harmless(amina, baraka, boss):
    eid = add(amina)["id"]
    assert boss.post(f"/api/review/{eid}/decline").status_code == 200
    again = boss.post(f"/api/review/{eid}/decline")
    assert again.status_code == 200
    assert again.json()["declined"] is True
    assert ids(baraka.get("/api/entries")) == []
    mine = amina.get(f"/api/entries/{eid}").json()
    assert mine["declined"] is True and mine["verification_status"] == "pending"
    assert boss.get("/api/review").json()["pending_count"] == 0


def test_declined_entries_do_not_count_toward_groups(amina, boss):
    eid = add(amina)["id"]
    boss.post(f"/api/review/{eid}/decline")
    numbers = {c["id"]: c["count"] for c in amina.get("/api/categories").json()}["numbers"]
    assert numbers == 0


def test_cannot_decline_an_approved_entry(amina, boss):
    eid = add(amina)["id"]
    boss.post(f"/api/review/{eid}/approve")
    assert boss.post(f"/api/review/{eid}/decline").status_code == 409


def test_admin_can_approve_a_previously_declined_entry(amina, baraka, boss):
    eid = add(amina)["id"]
    boss.post(f"/api/review/{eid}/decline")
    approved = boss.post(f"/api/review/{eid}/approve").json()
    assert approved["declined"] is False
    assert ids(baraka.get("/api/entries")) == [eid]


def test_member_edit_resubmits_a_declined_entry(amina, boss):
    eid = add(amina)["id"]
    boss.post(f"/api/review/{eid}/decline")
    fixed = amina.patch(f"/api/entries/{eid}", json={"english": "one (1)"}).json()
    assert fixed["declined"] is False
    assert [i["id"] for i in boss.get("/api/review").json()["items"]] == [eid]


def test_unknown_entry_is_404(boss):
    assert boss.post("/api/review/9999/approve").status_code == 404
    assert boss.post("/api/review/9999/decline").status_code == 404


def test_admin_native_verified_is_not_in_the_queue(amina, boss):
    eid = add(amina)["id"]
    boss.patch(f"/api/entries/{eid}", json={"verification_status": "native_verified"})
    assert boss.get("/api/review").json()["pending_count"] == 0
