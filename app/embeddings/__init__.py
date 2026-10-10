from app.config import Settings
from app.embeddings.base import Embedder


def build_embedder(settings: Settings) -> Embedder:
    """The embedder named by EMBEDDER. The real model is only imported when it is asked for."""
    if settings.embedder == "onnx":
        from app.embeddings.real import OnnxEmbedder

        return OnnxEmbedder(settings.embed_model_dir, settings.embed_model, settings.embed_threads)
    from app.embeddings.fake import FakeEmbedder

    return FakeEmbedder()
