"""Embedder interface.

Only the English side of an entry is ever embedded. Embedding models do not know Kigiriama, and
the vectors would be meaningless (and misleading) for it. Callers pass `entries.english` and
search queries, never `entries.giriama`.
"""

from abc import ABC, abstractmethod

EMBEDDING_DIM = 384  # matches entry_vec in migration 0001 (MiniLM-class models)


class Embedder(ABC):
    dim: int = EMBEDDING_DIM

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one unit-length vector of `dim` floats per text."""
