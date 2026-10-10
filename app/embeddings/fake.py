"""Deterministic embedder for tests and quick local runs: hashed bag of words.

Texts that share words get similar vectors, so tests can check that related wording ranks first.
It knows nothing about meaning, so it is not a substitute for the real model.
"""

import hashlib
import math
import re

from app.embeddings.base import Embedder

_WORD = re.compile(r"\w+")


class FakeEmbedder(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        words = _WORD.findall(text.lower()) or [text.lower()]
        for word in words:
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
