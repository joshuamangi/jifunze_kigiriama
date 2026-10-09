"""Print argon2id hash/verify time with the configured parameters. Re-run on the Pi to tune.

Run via `make bench-argon2`. Override with ARGON2_MEMORY_KIB, ARGON2_TIME_COST, ARGON2_PARALLELISM.
"""

import statistics
import time

from app.auth.hashing import PasswordService
from app.config import Settings

RUNS = 7


def main() -> None:
    settings = Settings.from_env()
    passwords = PasswordService(settings)
    hash_times, verify_times = [], []
    for _ in range(RUNS):
        start = time.perf_counter()
        encoded = passwords.hash("benchmark-password")
        hash_times.append(time.perf_counter() - start)
        start = time.perf_counter()
        passwords.verify(encoded, "benchmark-password")
        verify_times.append(time.perf_counter() - start)
    print(
        f"argon2id memory={settings.argon2_memory_kib} KiB "
        f"time_cost={settings.argon2_time_cost} parallelism={settings.argon2_parallelism}"
    )
    print(f"hash   median {statistics.median(hash_times) * 1000:.0f} ms over {RUNS} runs")
    print(f"verify median {statistics.median(verify_times) * 1000:.0f} ms over {RUNS} runs")


if __name__ == "__main__":
    main()
