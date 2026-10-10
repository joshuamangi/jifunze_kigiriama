"""Rebuild every vector from entries.english. Run: make reindex

Marks all entries as needing an embedding, then embeds them in this process with the configured
embedder (EMBEDDER=fake|onnx). Only English text is embedded. Safe to stop and re-run: progress is
kept in entries.embedded_at.
"""

import argparse
import resource
import sys
import time

from app.config import Settings
from app.db import Database
from app.embeddings import build_embedder
from app.embeddings.worker import EmbeddingWorker


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024  # bytes vs KiB


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild all entry vectors")
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args()

    settings = Settings.from_env()
    db = Database(settings.database_path, readers=1)
    try:
        print(f"embedder={settings.embedder} model={settings.embed_model}")
        loaded = time.perf_counter()
        embedder = build_embedder(settings)
        print(f"model ready in {time.perf_counter() - loaded:.2f}s")
        with db.write() as conn:
            conn.execute("DELETE FROM entry_vec")
            conn.execute("UPDATE entries SET embedded_at = NULL")
        started = time.perf_counter()
        done = EmbeddingWorker(db, embedder, batch_size=args.batch).process_pending()
        took = time.perf_counter() - started
        rate = done / took if took else 0.0
        print(f"embedded {done} entries in {took:.2f}s ({rate:.1f}/s)")
        print(f"peak RSS {peak_rss_mb():.0f} MB")
    finally:
        db.close()


if __name__ == "__main__":
    main()
