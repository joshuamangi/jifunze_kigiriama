"""Login throttle, per account and per source address, with growing delays.

In memory: the app runs a single process, so one lock is enough. A restart clears the counters;
Nginx rate limiting (Stage 8) is the second layer.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

FREE_FAILURES = 5  # failures allowed before a delay starts
BASE_DELAY = 30.0  # seconds, doubles with each further failure
MAX_DELAY = 15 * 60.0
MAX_KEYS = 10_000  # bound on tracked keys so memory cannot grow without limit
FORGET_AFTER = 24 * 3600.0


@dataclass
class _Entry:
    failures: int = 0
    blocked_until: float = 0.0
    last_failure: float = 0.0


class LoginThrottle:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    @staticmethod
    def _keys(username: str, address: str) -> list[str]:
        return [f"user:{username.strip().lower()}", f"addr:{address}"]

    def retry_after(self, username: str, address: str) -> int:
        """Seconds the caller must wait, or 0 when allowed."""
        now = self._clock()
        with self._lock:
            waits = [
                self._entries[k].blocked_until - now
                for k in self._keys(username, address)
                if k in self._entries
            ]
        longest = max(waits, default=0.0)
        return int(longest) + 1 if longest > 0 else 0

    def record_failure(self, username: str, address: str) -> None:
        now = self._clock()
        with self._lock:
            self._prune(now)
            for key in self._keys(username, address):
                entry = self._entries.setdefault(key, _Entry())
                entry.failures += 1
                entry.last_failure = now
                over = entry.failures - FREE_FAILURES
                if over >= 0:
                    entry.blocked_until = now + min(BASE_DELAY * 2**over, MAX_DELAY)

    def record_success(self, username: str) -> None:
        """A good login clears the account counter; the address counter is left to expire."""
        with self._lock:
            self._entries.pop(f"user:{username.strip().lower()}", None)

    def _prune(self, now: float) -> None:
        if len(self._entries) < MAX_KEYS:
            return
        stale = [
            k
            for k, e in self._entries.items()
            if e.blocked_until <= now and now - e.last_failure > FORGET_AFTER
        ]
        for key in stale:
            del self._entries[key]
        if len(self._entries) >= MAX_KEYS:  # still full: drop the oldest quarter
            oldest = sorted(self._entries, key=lambda k: self._entries[k].last_failure)
            for key in oldest[: MAX_KEYS // 4]:
                del self._entries[key]
