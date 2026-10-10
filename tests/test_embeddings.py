import math
import struct
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.embeddings import build_embedder
from app.embeddings.base import EMBEDDING_DIM, Embedder
from app.embeddings.fake import FakeEmbedder
from app.embeddings.worker import EmbeddingWorker
from app.main import create_app
from tests.helpers import GUARD_HEADERS


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def add_entry(db, giriama, english, uid=None):
    with db.write() as conn:
        cur = conn.execute(
            "INSERT INTO entries (giriama, english, category, source_type, verification_status,"
            " created_by) VALUES (?, ?, 'numbers', 'dictionary', 'unverified', ?)",
            (giriama, english, uid),
        )
        return cur.lastrowid


def embedded(db):
    with db.read() as conn:
        return {
            r["id"]: r["embedded_at"] for r in conn.execute("SELECT id, embedded_at FROM entries")
        }


def vec_ids(db):
    with db.read() as conn:
        return {r[0] for r in conn.execute("SELECT entry_id FROM entry_vec")}


class SpyEmbedder(Embedder):
    def __init__(self):
        self.seen: list[str] = []
        self._inner = FakeEmbedder()

    def embed(self, texts):
        self.seen += texts
        return self._inner.embed(texts)


# ---- the fake embedder ---------------------------------------------------------------------
def test_fake_vectors_are_deterministic_unit_length_and_384d():
    fake = FakeEmbedder()
    first, again = fake.embed(["two numbers"])[0], fake.embed(["two numbers"])[0]
    assert first == again
    assert len(first) == EMBEDDING_DIM == 384
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-6)


def test_fake_vectors_share_similarity_when_words_overlap():
    a, b, c = FakeEmbedder().embed(["two things", "two", "goat"])
    assert cosine(a, b) > cosine(a, c)


# ---- worker behaviour ----------------------------------------------------------------------
def test_save_returns_before_embedding_then_worker_fills_the_vector(app, login_as, db):
    client = login_as("boss", "admin")
    body = {"giriama": "mwenga", "english": "one", "category": "numbers", "source_type": "own"}
    assert client.post("/api/entries", json=body).status_code == 201
    assert embedded(db)[1] is None and vec_ids(db) == set()  # no worker has run yet

    assert EmbeddingWorker(db, FakeEmbedder()).process_pending() == 1
    assert embedded(db)[1] is not None and vec_ids(db) == {1}


def test_a_full_queue_never_blocks_a_save(db):
    worker = EmbeddingWorker(db, FakeEmbedder(), queue_size=1)
    started = time.perf_counter()
    for entry_id in range(50):
        worker.notify(entry_id)  # 49 of these find the queue full
    assert time.perf_counter() - started < 0.5


def test_a_restarted_worker_resumes_from_embedded_at_null(db):
    ids = [add_entry(db, g, e) for g, e in (("mwenga", "one"), ("hiri", "two"), ("hahu", "three"))]
    assert all(v is None for v in embedded(db).values())

    worker = EmbeddingWorker(db, FakeEmbedder(), rescan_seconds=0.05)  # "after a restart"
    worker.start()
    deadline = time.time() + 5
    while time.time() < deadline and None in embedded(db).values():
        time.sleep(0.02)
    worker.stop()
    assert vec_ids(db) == set(ids)
    assert None not in embedded(db).values()


def test_worker_stops_promptly(db):
    worker = EmbeddingWorker(db, FakeEmbedder(), rescan_seconds=30)
    worker.start()
    started = time.perf_counter()
    worker.stop()
    assert time.perf_counter() - started < 2


def test_an_edit_made_during_embedding_is_not_marked_done_and_is_redone(db):
    eid = add_entry(db, "mwenga", "one")

    class EditsWhileEmbedding(FakeEmbedder):
        done = False

        def embed(self, texts):
            if not self.done:
                self.done = True
                with db.write() as conn:  # a user edits the English while we are computing
                    conn.execute(
                        "UPDATE entries SET english = 'the number one', embedded_at = NULL"
                        " WHERE id = ?",
                        (eid,),
                    )
            return super().embed(texts)

    worker = EmbeddingWorker(db, EditsWhileEmbedding())
    worker.process_pending()
    assert embedded(db)[eid] is None and vec_ids(db) == set()  # stale vector not stored
    worker.process_pending()
    assert embedded(db)[eid] is not None
    with db.read() as conn:
        stored = conn.execute(
            "SELECT embedding FROM entry_vec WHERE entry_id = ?", (eid,)
        ).fetchone()
    expected = FakeEmbedder().embed(["the number one"])[0]
    assert list(struct.unpack(f"{EMBEDDING_DIM}f", stored[0])) == pytest.approx(expected, abs=1e-6)


def test_kigiriama_text_never_reaches_the_embedder(db):
    for giriama, english in (("mwenga", "one"), ("hiri", "two"), ("kumi na hahu", "thirteen")):
        add_entry(db, giriama, english)
    spy = SpyEmbedder()
    EmbeddingWorker(db, spy).process_pending()
    assert sorted(spy.seen) == ["one", "thirteen", "two"]
    for kigiriama in ("mwenga", "hiri", "kumi na hahu"):
        assert not any(kigiriama in seen for seen in spy.seen)


def test_an_embedder_error_does_not_kill_the_worker_and_is_retried(db):
    add_entry(db, "mwenga", "one")

    class FailsOnce(FakeEmbedder):
        calls = 0

        def embed(self, texts):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("model hiccup")
            return super().embed(texts)

    worker = EmbeddingWorker(db, FailsOnce(), rescan_seconds=0.05)
    worker.start()
    deadline = time.time() + 5
    while time.time() < deadline and None in embedded(db).values():
        time.sleep(0.02)
    worker.stop()
    assert None not in embedded(db).values()


def test_api_save_wakes_the_running_worker(settings, db, login_as_factory=None):
    app = create_app(settings, db, embedder=FakeEmbedder(), start_worker=True)
    with TestClient(app, headers=GUARD_HEADERS) as client:
        from app.users import create_user

        create_user(db, app.state.passwords, "boss", "correct horse battery", "admin")
        client.post("/api/login", json={"username": "boss", "password": "correct horse battery"})
        body = {"giriama": "hiri", "english": "two", "category": "numbers", "source_type": "own"}
        assert client.post("/api/entries", json=body).status_code == 201
        deadline = time.time() + 5
        while time.time() < deadline and None in embedded(db).values():
            time.sleep(0.02)
        assert None not in embedded(db).values()
    assert not any(t.name == "embedding-worker" and t.is_alive() for t in threading.enumerate())


# ---- configuration -------------------------------------------------------------------------
def test_embedder_settings_default_to_the_fake_and_reject_unknown_values():
    s = Settings.from_env({})
    assert (s.embedder, s.embed_model, s.embed_threads) == ("fake", "fp32", 2)
    assert isinstance(build_embedder(s), FakeEmbedder)
    for bad in ({"EMBEDDER": "gpt"}, {"EMBED_MODEL": "int4"}, {"EMBED_THREADS": "0"}):
        with pytest.raises(ConfigError):
            Settings.from_env(bad)


def test_the_real_embedder_fails_fast_with_instructions_when_the_model_is_missing(tmp_path, db):
    settings = Settings.from_env({"EMBEDDER": "onnx", "EMBED_MODEL_DIR": str(tmp_path / "nothing")})
    app = create_app(settings, db, start_worker=False)
    with pytest.raises(RuntimeError, match="make download-model"), TestClient(app):
        pass


# ---- the real model (only when the files have been downloaded) -----------------------------
MODELS = Path(__file__).resolve().parent.parent / "models"
have_model = (MODELS / "model.onnx").is_file() and (MODELS / "tokenizer.json").is_file()


@pytest.mark.skipif(not have_model, reason="run `make download-model` to enable")
def test_real_model_vectors_are_384d_unit_length_and_semantically_ordered():
    from app.embeddings.real import OnnxEmbedder

    embedder = OnnxEmbedder(MODELS, "fp32", threads=2)
    two, three, goat = embedder.embed(["two", "three", "goat"])
    assert len(two) == 384
    assert math.isclose(math.sqrt(sum(v * v for v in two)), 1.0, rel_tol=1e-4)
    assert cosine(two, three) > cosine(two, goat)
    animals, dog, car = embedder.embed(["animals", "dog", "car"])
    assert cosine(animals, dog) > cosine(animals, car)


@pytest.mark.skipif(
    not (MODELS / "model_qint8_arm64.onnx").is_file(), reason="qint8 model not downloaded"
)
def test_quantised_model_keeps_the_same_ordering():
    from app.embeddings.real import OnnxEmbedder

    embedder = OnnxEmbedder(MODELS, "qint8", threads=2)
    two, three, goat = embedder.embed(["two", "three", "goat"])
    assert cosine(two, three) > cosine(two, goat)
