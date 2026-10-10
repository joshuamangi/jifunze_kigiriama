"""Background worker that fills entry_vec from entries.english.

State lives in the table: entries.embedded_at IS NULL means "needs a vector". A restart simply
scans for NULLs and carries on, so no broker or in-memory queue has to survive. The queue is only
a hint to wake the worker quickly; if it is full, the periodic rescan covers the gap.
"""

import logging
import queue
import struct
import threading

from app.db import Database
from app.embeddings.base import Embedder

log = logging.getLogger("jifunze.embeddings")

QUEUE_SIZE = 256
BATCH_SIZE = 16
RESCAN_SECONDS = 30.0
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class EmbeddingWorker:
    def __init__(
        self,
        db: Database,
        embedder: Embedder,
        rescan_seconds: float = RESCAN_SECONDS,
        batch_size: int = BATCH_SIZE,
        queue_size: int = QUEUE_SIZE,
    ) -> None:
        self._db = db
        self._embedder = embedder
        self._rescan = rescan_seconds
        self._batch = batch_size
        self._queue: queue.Queue[int] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- called from request handlers: never blocks ------------------------------------------
    def notify(self, entry_id: int) -> None:
        try:
            self._queue.put_nowait(entry_id)
        except queue.Full:
            pass  # the periodic rescan will find it

    # ---- lifecycle ----------------------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="embedding-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(-1)  # wake the loop
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout)
            self._thread = None

    # ---- the work -----------------------------------------------------------------------------
    def process_pending(self) -> int:
        """Embed every entry that still needs it, in batches. Returns how many were stored."""
        stored = 0
        while not self._stop.is_set():
            with self._db.read() as conn:
                rows = conn.execute(
                    "SELECT id, english FROM entries WHERE embedded_at IS NULL ORDER BY id LIMIT ?",
                    (self._batch,),
                ).fetchall()
            if not rows:
                break
            done = self._store([(r["id"], r["english"]) for r in rows])
            stored += done
            if done == 0 and len(rows) < self._batch:
                break  # everything left was edited meanwhile; the next pass redoes it
            if done == 0:
                break  # avoid spinning on rows that keep changing
        return stored

    def _store(self, items: list[tuple[int, str]]) -> int:
        # Only the English text goes to the embedder. Kigiriama text is never read here.
        vectors = self._embedder.embed([english for _, english in items])
        stored = 0
        with self._db.write() as conn:
            for (entry_id, english), vector in zip(items, vectors, strict=True):
                # Mark done only if the English text is still what we embedded; an edit made
                # while we were working leaves embedded_at NULL so the entry is redone.
                cur = conn.execute(
                    f"UPDATE entries SET embedded_at = {NOW} WHERE id = ? AND english = ?",
                    (entry_id, english),
                )
                if cur.rowcount != 1:
                    continue
                conn.execute("DELETE FROM entry_vec WHERE entry_id = ?", (entry_id,))
                conn.execute(
                    "INSERT INTO entry_vec (entry_id, embedding) VALUES (?, ?)",
                    (entry_id, pack(vector)),
                )
                stored += 1
        return stored

    def _run(self) -> None:
        self._safely(self.process_pending)  # resume after a restart
        while not self._stop.is_set():
            try:
                self._queue.get(timeout=self._rescan)
            except queue.Empty:
                pass
            if self._stop.is_set():
                break
            while True:  # drain the hints; the table scan below is the source of truth
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._safely(self.process_pending)

    def _safely(self, fn) -> None:
        try:
            fn()
        except Exception:  # a bad batch must not kill the worker; it is retried on the next scan
            log.exception("embedding pass failed")
