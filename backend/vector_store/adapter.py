from backend.config import settings
from backend.vector_store.models import StoreEngine
import sys

if settings.DEFAULT_VECTOR_DB == StoreEngine.LANCE:
    import backend.vector_store.lance_db as vector_store
elif settings.DEFAULT_VECTOR_DB == StoreEngine.CHROMA:
    import backend.vector_store.chroma_db as vector_store
elif settings.DEFAULT_VECTOR_DB == StoreEngine.MILVUS_LITE:
    import backend.vector_store.milvus_db as vector_store


def _wrap_embeddings(vs):
    if vs is not None and hasattr(vs, "embeddings"):
        from backend.core.embedding_cache import CachedEmbedder
        if not isinstance(vs.embeddings, CachedEmbedder):
            vs.embeddings = CachedEmbedder(vs.embeddings)
    return vs


_wrap_embeddings(vector_store)


def vector_db():
    for name in ("backend.vector_store.lance_db", "backend.vector_store.chroma_db", "backend.vector_store.milvus_db"):
        mod = sys.modules.get(name)
        if mod is not None:
            _wrap_embeddings(mod)
    return _wrap_embeddings(vector_store)
