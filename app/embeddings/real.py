"""The real embedder: all-MiniLM-L6-v2 through ONNX Runtime on the CPU.

Why ONNX Runtime and not a GGUF runtime: onnxruntime, tokenizers and numpy all ship aarch64
wheels, so nothing has to be compiled on the Raspberry Pi. Same model family, same 384 dims.
The model is loaded once (at startup) and shared; a lock keeps inference to one call at a time so
memory use stays predictable.
"""

import threading
from pathlib import Path

from app.embeddings.base import Embedder

MODEL_FILES = {"fp32": "model.onnx", "qint8": "model_qint8_arm64.onnx"}
TOKENIZER_FILE = "tokenizer.json"
MAX_TOKENS = 256  # the model's limit; entries are a word or a short phrase


class ModelMissingError(RuntimeError):
    pass


def model_paths(model_dir: str | Path, variant: str) -> tuple[Path, Path]:
    base = Path(model_dir)
    return base / MODEL_FILES[variant], base / TOKENIZER_FILE


class OnnxEmbedder(Embedder):
    def __init__(self, model_dir: str | Path, variant: str = "fp32", threads: int = 2) -> None:
        model_path, tokenizer_path = model_paths(model_dir, variant)
        missing = [p for p in (model_path, tokenizer_path) if not p.is_file()]
        if missing:
            raise ModelMissingError(
                f"embedding model file(s) missing: {', '.join(str(p) for p in missing)}. "
                "Run `make download-model`."
            )
        # Imported here so the app starts (and the tests run) without loading onnxruntime.
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self._tokenizer.enable_padding()
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        np = self._np
        with self._lock:
            encoded = self._tokenizer.encode_batch(texts)
            feeds = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in encoded], dtype=np.int64),
            }
            feeds = {k: v for k, v in feeds.items() if k in self._input_names}
            hidden = self._session.run(None, feeds)[0]  # (batch, tokens, 384)
        mask = feeds["attention_mask"][:, :, None].astype(hidden.dtype)
        pooled = (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
        norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        return (pooled / norms).astype("float32").tolist()
