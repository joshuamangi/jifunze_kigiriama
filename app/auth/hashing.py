"""argon2id password hashing with a small concurrency cap (hashing is memory hungry)."""

import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings

# Number of simultaneous hash/verify operations; keeps a burst of logins from exhausting RAM.
MAX_CONCURRENT_HASHES = 2


class PasswordService:
    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)
        # Verified against when the username does not exist, so timing does not reveal accounts.
        self._dummy_hash = self.hash("not-a-real-password")

    def hash(self, password: str) -> str:
        with self._slots:
            return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        with self._slots:
            try:
                return self._hasher.verify(password_hash, password)
            except (VerificationError, InvalidHashError):
                return False

    def verify_unknown_user(self, password: str) -> bool:
        """Spend the same time as a real check, then report failure."""
        self.verify(self._dummy_hash, password)
        return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)
