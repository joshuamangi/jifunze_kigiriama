"""Measure the embedding model: load time, per-embedding latency, peak memory. Run: make bench-embed

Run it on the Raspberry Pi as well as on your Mac; the Pi numbers are the ones that matter.
Uses made-up English words only (no Kigiriama).

  python scripts/bench_embed.py                 # EMBED_MODEL from the environment (default fp32)
  python scripts/bench_embed.py --variant qint8
  python scripts/bench_embed.py --variant all   # compare fp32 and qint8 and their agreement
"""

import argparse
import os
import resource
import statistics
import sys
import time

from app.embeddings.real import OnnxEmbedder

WORDS = [
    "house",
    "water",
    "river",
    "mother",
    "market",
    "morning",
    "goat",
    "number",
    "greeting",
    "food",
]
PAIRS = [("two", "three", "goat"), ("dog", "animal", "car"), ("mother", "father", "bicycle")]


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def bench(variant: str, model_dir: str, threads: int, runs: int) -> dict:
    started = time.perf_counter()
    embedder = OnnxEmbedder(model_dir, variant, threads)
    load = time.perf_counter() - started
    embedder.embed(["warm up"])
    single = []
    for i in range(runs):
        t = time.perf_counter()
        embedder.embed([WORDS[i % len(WORDS)]])
        single.append((time.perf_counter() - t) * 1000)
    batch_text = [f"{w} {i}" for i, w in enumerate(WORDS * 6)][:64]
    t = time.perf_counter()
    embedder.embed(batch_text)
    batch = (time.perf_counter() - t) * 1000
    single.sort()
    agreement = [
        cosine(*embedder.embed([a, b])) - cosine(*embedder.embed([a, c])) for a, b, c in PAIRS
    ]
    print(f"--- {variant} (threads={threads})")
    print(
        f"load {load:.2f}s | per embedding median {statistics.median(single):.1f} ms, "
        f"p95 {single[int(len(single) * 0.95) - 1]:.1f} ms"
    )
    print(f"batch of {len(batch_text)}: {batch:.0f} ms ({batch / len(batch_text):.1f} ms each)")
    print(f"peak RSS so far {peak_rss_mb():.0f} MB")
    print(
        "related minus unrelated similarity (should be > 0):",
        ", ".join(f"{a:.2f}" for a in agreement),
    )
    return {"embedder": embedder}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the embedding model")
    parser.add_argument(
        "--variant", choices=["fp32", "qint8", "all"], default=os.environ.get("EMBED_MODEL", "fp32")
    )
    parser.add_argument("--dir", default=os.environ.get("EMBED_MODEL_DIR", "models"))
    parser.add_argument("--threads", type=int, default=int(os.environ.get("EMBED_THREADS", "2")))
    parser.add_argument("--runs", type=int, default=50)
    args = parser.parse_args()
    variants = ["fp32", "qint8"] if args.variant == "all" else [args.variant]
    for variant in variants:
        bench(variant, args.dir, args.threads, args.runs)


if __name__ == "__main__":
    main()
