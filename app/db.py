"""SQLite connections: pragmas, sqlite-vec, a small read pool and a single guarded writer."""

import queue
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

DEFAULT_READERS = 4


def connect(path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection with the project's pragmas and sqlite-vec loaded.

    Transactions are explicit (isolation_level=None): callers issue BEGIN/COMMIT themselves.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if read_only:
        conn.execute("PRAGMA query_only = ON")
    return conn


class Database:
    """One write connection behind a lock, plus a few read connections (WAL lets readers run
    alongside the writer). Writers queue on the lock instead of failing with 'database is locked'.
    """

    def __init__(self, path: str | Path, readers: int = DEFAULT_READERS) -> None:
        self.path = path
        self._write_lock = threading.Lock()
        self._writer = connect(path)
        self._readers: queue.Queue[sqlite3.Connection] = queue.Queue()
        for _ in range(readers):
            self._readers.put(connect(path, read_only=True))

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._readers.get()
        try:
            yield conn
        finally:
            self._readers.put(conn)

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Short write transaction: BEGIN IMMEDIATE, commit on success, roll back on error."""
        with self._write_lock:
            self._writer.execute("BEGIN IMMEDIATE")
            try:
                yield self._writer
            except BaseException:
                self._writer.execute("ROLLBACK")
                raise
            else:
                self._writer.execute("COMMIT")

    def close(self) -> None:
        with self._write_lock:
            self._writer.close()
        while not self._readers.empty():
            self._readers.get_nowait().close()
