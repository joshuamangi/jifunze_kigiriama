"""Download the embedding model into models/ and verify its SHA-256. Run: make download-model

The model is all-MiniLM-L6-v2 (Apache-2.0) from Hugging Face, pinned to one revision so the files
(and their checksums) cannot change under us. The files are not stored in git.

  python scripts/download_model.py            # the variant named by EMBED_MODEL (default fp32)
  python scripts/download_model.py --variant qint8
  python scripts/download_model.py --variant all
"""

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
BASE = f"https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{REVISION}"

# local name -> (path in the repo, size in bytes, sha256)
FILES = {
    "model.onnx": (
        "onnx/model.onnx",
        90405214,
        "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    ),
    "model_qint8_arm64.onnx": (
        "onnx/model_qint8_arm64.onnx",
        23026053,
        "4278337fd0ff3c68bfb6291042cad8ab363e1d9fbc43dcb499fe91c871902474",
    ),
    "tokenizer.json": (
        "tokenizer.json",
        466247,
        "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    ),
}
VARIANTS = {"fp32": ["model.onnx"], "qint8": ["model_qint8_arm64.onnx"]}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str, target_dir: Path) -> None:
    repo_path, size, expected = FILES[name]
    target = target_dir / name
    if target.is_file() and sha256_of(target) == expected:
        print(f"ok (already verified): {target}")
        return
    print(f"downloading {name} ({size / 1_048_576:.1f} MB) ...")
    partial = target.with_suffix(target.suffix + ".part")
    url = f"{BASE}/{repo_path}"  # https and a fixed host, built from the constants above
    with (
        urllib.request.urlopen(url, timeout=60) as response,  # noqa: S310
        partial.open("wb") as out,
    ):
        for block in iter(lambda: response.read(1 << 20), b""):
            out.write(block)
    actual = sha256_of(partial)
    if actual != expected:
        partial.unlink()
        sys.exit(f"CHECKSUM MISMATCH for {name}: expected {expected}, got {actual}. File removed.")
    partial.replace(target)
    print(f"verified: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the embedding model")
    parser.add_argument(
        "--variant", choices=[*VARIANTS, "all"], default=os.environ.get("EMBED_MODEL", "fp32")
    )
    parser.add_argument("--dir", default=os.environ.get("EMBED_MODEL_DIR", "models"))
    args = parser.parse_args()
    target_dir = Path(args.dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    names = (
        [n for v in VARIANTS.values() for n in v]
        if args.variant == "all"
        else VARIANTS[args.variant]
    )
    for name in [*names, "tokenizer.json"]:
        fetch(name, target_dir)


if __name__ == "__main__":
    main()
