import pytest
from fastapi.testclient import TestClient

from app.embeddings.fake import FakeEmbedder
from app.embeddings.worker import EmbeddingWorker
from tests.helpers import GUARD_HEADERS
from tests.test_entries_api import ONE, THIRTEEN, THREE, TWO, add


@pytest.fixture
def amina(login_as):
    return login_as("amina")


@pytest.fixture
def baraka(login_as):
    return login_as("baraka")


@pytest.fixture
def boss(login_as):
    return login_as("boss", "admin")


@pytest.fixture
def index(db):
    """Run the embedding worker once, synchronously."""
    return lambda: EmbeddingWorker(db, FakeEmbedder()).process_pending()


def search(client, q, mode="semantic", **params):
    return client.get("/api/search", params={"q": q, "mode": mode, **params})


def english(response):
    return [item["english"] for item in response.json()["items"]]


# ---- keyword -------------------------------------------------------------------------------
def test_keyword_search_finds_english_and_kigiriama_text_ranked(boss):
    add(boss, THIRTEEN)
    add(boss, {**TWO, "english": "two and two again"})
    add(boss, TWO)
    by_english = search(boss, "two", "keyword")
    assert by_english.status_code == 200
    body = by_english.json()
    assert body["mode"] == "keyword" and body["not_yet_indexed"] is None
    assert len(body["items"]) == 2
    assert all("score" in item for item in body["items"])
    assert [i["giriama"] for i in search(boss, "kumi hahu", "keyword").json()["items"]] == [
        "kumi na hahu"
    ]


def test_keyword_search_needs_no_embeddings(boss):
    add(boss, ONE)
    assert english(search(boss, "one", "keyword")) == ["one"]


@pytest.mark.parametrize("q", ['"', "a OR", "NEAR(", "*", "'; DROP TABLE entries;--", "(", "^"])
def test_search_text_never_breaks_either_mode(boss, q):
    add(boss, ONE)
    for mode in ("keyword", "semantic"):
        assert search(boss, q, mode).status_code == 200
    assert boss.get("/api/entries").json()["total"] == 1


# ---- semantic ------------------------------------------------------------------------------
def test_semantic_search_ranks_related_wording_first(boss, index):
    add(boss, THREE)
    add(boss, TWO)
    add(boss, ONE)
    add(boss, {**THIRTEEN, "english": "two things together"})
    index()
    body = search(boss, "two").json()
    assert body["not_yet_indexed"] == 0
    assert [i["english"] for i in body["items"]][:2] == ["two", "two things together"]
    scores = [i["score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)


def test_not_yet_indexed_explains_an_empty_result(boss, index):
    add(boss, ONE)
    add(boss, TWO)
    body = search(boss, "one").json()
    assert body["items"] == [] and body["not_yet_indexed"] == 2
    index()
    assert search(boss, "one").json()["not_yet_indexed"] == 0


def test_an_edit_makes_the_entry_unsearchable_until_it_is_reindexed(boss, index):
    eid = add(boss, ONE)["id"]
    index()
    assert english(search(boss, "one")) == ["one"]
    boss.patch(f"/api/entries/{eid}", json={"english": "goat"})
    assert search(boss, "goat").json()["not_yet_indexed"] == 1
    index()
    assert english(search(boss, "goat"))[0] == "goat"


def test_limit_is_respected(boss, index):
    for n in range(6):
        add(boss, {**ONE, "english": f"two word {n}"})
    index()
    assert len(search(boss, "two", limit=3).json()["items"]) == 3


# ---- visibility (both modes) ---------------------------------------------------------------
@pytest.mark.parametrize("mode", ["keyword", "semantic"])
def test_a_member_never_finds_another_members_pending_or_declined_entry(
    amina, baraka, boss, index, mode
):
    pending = add(amina, ONE)["id"]
    declined = add(amina, {**TWO, "english": "one more"})["id"]
    boss.post(f"/api/review/{declined}/decline")
    index()
    assert search(baraka, "one", mode).json()["items"] == []
    assert {i["id"] for i in search(amina, "one", mode).json()["items"]} == {pending, declined}
    assert {i["id"] for i in search(boss, "one", mode).json()["items"]} == {pending, declined}
    boss.post(f"/api/review/{pending}/approve")
    assert [i["id"] for i in search(baraka, "one", mode).json()["items"]] == [pending]


def test_hidden_entries_do_not_crowd_out_visible_ones(amina, baraka, boss, index):
    # Ten of amina's pending entries are closer to the query than the one approved entry, so a
    # naive "take the top 1 then filter" would return nothing to baraka.
    for _ in range(10):
        add(amina, {**ONE, "english": "two"})
    approved = add(boss, {**TWO, "english": "two things together"})["id"]
    index()
    body = search(baraka, "two", limit=1).json()
    assert [i["id"] for i in body["items"]] == [approved]


def test_not_yet_indexed_counts_only_what_the_caller_can_see(amina, baraka):
    add(amina, ONE)
    assert search(amina, "one").json()["not_yet_indexed"] == 1
    assert search(baraka, "one").json()["not_yet_indexed"] == 0


# ---- input and access ----------------------------------------------------------------------
def test_validation(boss):
    assert boss.get("/api/search").status_code == 422
    assert boss.get("/api/search", params={"q": ""}).status_code == 422
    assert boss.get("/api/search", params={"q": "x" * 201}).status_code == 422
    assert boss.get("/api/search", params={"q": "a", "mode": "fuzzy"}).status_code == 422
    assert boss.get("/api/search", params={"q": "a", "limit": 0}).status_code == 422
    assert boss.get("/api/search", params={"q": "a", "limit": 51}).status_code == 422


def test_anonymous_search_is_rejected(app):
    assert (
        TestClient(app, headers=GUARD_HEADERS).get("/api/search", params={"q": "a"}).status_code
        == 401
    )
