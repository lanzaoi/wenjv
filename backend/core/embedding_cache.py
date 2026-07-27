# backend/core/embedding_cache.py
import hashlib
from typing import Optional, Any, List
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import delete

from backend.database import get_cache_engine, EmbedCacheTable
from backend.core.logging import get_logger
from backend.config import settings

logger = get_logger()


class EmbeddingCache:
    """
    SQLite-backed embedding cache to prevent re-embedding identical text.
    Composite primary key (text_hash, model) ensures distinct models do not share vectors.
    """

    def __init__(self):
        try:
            EmbedCacheTable.__table__.create(bind=get_cache_engine(), checkfirst=True)
        except Exception:
            pass

    @staticmethod
    def hash(text: str) -> str:
        """
        Hash text using SHA-256 first 16 bytes (represented as 16 hex characters).
        """
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def get(self, text: str, model: str) -> Optional[np.ndarray]:
        """
        Retrieve cached vector for (text, model). Returns Optional[np.ndarray].
        """
        if not getattr(settings, "EMBEDDING_CACHE_ENABLED", True):
            return None
        if not text or not model:
            return None
        text_hash = self.hash(text)
        with Session(get_cache_engine()) as session:
            row = session.get(EmbedCacheTable, (text_hash, model))
            if row and row.vector:
                try:
                    arr = np.frombuffer(row.vector, dtype=np.float32)
                    return arr.copy()
                except Exception:
                    return None
        return None

    def set(self, text: str, model: str, vector: Any) -> None:
        """
        Store vector for (text, model) in embed_cache table.
        """
        if not getattr(settings, "EMBEDDING_CACHE_ENABLED", True):
            return
        if not text or not model or vector is None:
            return
        text_hash = self.hash(text)
        try:
            arr = np.array(vector, dtype=np.float32)
            blob = arr.tobytes()
        except Exception:
            return

        with Session(get_cache_engine()) as session:
            try:
                row = session.get(EmbedCacheTable, (text_hash, model))
                if row:
                    row.vector = blob
                else:
                    new_row = EmbedCacheTable(
                        text_hash=text_hash,
                        model=model,
                        vector=blob,
                    )
                    session.add(new_row)
                session.commit()
            except Exception:
                session.rollback()
                try:
                    row = session.get(EmbedCacheTable, (text_hash, model))
                    if row:
                        row.vector = blob
                        session.commit()
                except Exception:
                    session.rollback()

    def clear(self, model: Optional[str] = None) -> None:
        """
        Clear cache entries. If model is None, clear entire table.
        """
        with Session(get_cache_engine()) as session:
            if model is None:
                session.execute(delete(EmbedCacheTable))
            else:
                session.execute(delete(EmbedCacheTable).where(EmbedCacheTable.model == model))
            session.commit()


class CachedEmbedder:
    """
    Wrapper around an embedding model that adds caching via EmbeddingCache.
    Implements fail-open behavior: if cache operations fail, logs a warning and falls back to API.
    """

    def __init__(self, embedder: Any, cache: Optional[EmbeddingCache] = None):
        self._embedder = embedder
        try:
            self._cache = cache if cache is not None else EmbeddingCache()
        except Exception as e:
            logger.warning(f"Failed to initialize EmbeddingCache in CachedEmbedder (fail-open): {e}")
            self._cache = None

    def _get_model_name(self) -> str:
        from backend.config import settings
        return getattr(self._embedder, "model", None) or getattr(settings, "EMBEDDINGS_MODEL", "default")

    def embed_query(self, text: str) -> List[float]:
        if not text:
            return []
        if not getattr(settings, "EMBEDDING_CACHE_ENABLED", True):
            return self._embedder.embed_query(text)
        model = self._get_model_name()
        
        # 1. Check cache
        if self._cache is not None:
            try:
                cached_vec = self._cache.get(text, model)
                if cached_vec is not None:
                    return cached_vec.tolist()
            except Exception as e:
                logger.warning(f"EmbeddingCache get failed for query (fail-open): {e}")

        # 2. Call underlying API
        vector = self._embedder.embed_query(text)

        # 3. Write to cache
        if self._cache is not None:
            try:
                self._cache.set(text, model, vector)
            except Exception as e:
                logger.warning(f"EmbeddingCache set failed for query (fail-open): {e}")

        return vector

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not getattr(settings, "EMBEDDING_CACHE_ENABLED", True):
            return self._embedder.embed_documents(texts)
        model = self._get_model_name()
        
        results: List[Optional[List[float]]] = [None] * len(texts)
        missing_indices: List[int] = []
        missing_texts: List[str] = []

        # 1. Check cache for each document
        if self._cache is not None:
            for i, text in enumerate(texts):
                try:
                    cached_vec = self._cache.get(text, model)
                    if cached_vec is not None:
                        results[i] = cached_vec.tolist()
                    else:
                        missing_indices.append(i)
                        missing_texts.append(text)
                except Exception as e:
                    logger.warning(f"EmbeddingCache get failed for doc index {i} (fail-open): {e}")
                    missing_indices.append(i)
                    missing_texts.append(text)
        else:
            missing_indices = list(range(len(texts)))
            missing_texts = list(texts)

        # 2. If all hit in cache, return immediately without calling API!
        if not missing_indices:
            return results  # type: ignore

        # Deduplicate texts to fetch from API
        unique_texts: List[str] = []
        seen = set()
        for t in missing_texts:
            if t not in seen:
                seen.add(t)
                unique_texts.append(t)

        # 3. Call API only for missing texts
        api_vectors = self._embedder.embed_documents(unique_texts)
        
        if len(api_vectors) == len(unique_texts):
            vec_map = dict(zip(unique_texts, api_vectors))
            for idx, text in zip(missing_indices, missing_texts):
                vec = vec_map[text]
                results[idx] = vec
                if self._cache is not None:
                    try:
                        self._cache.set(text, model, vec)
                    except Exception as e:
                        logger.warning(f"EmbeddingCache set failed for doc index {idx} (fail-open): {e}")
        else:
            # Fallback if API returned mismatched length
            api_vectors = self._embedder.embed_documents(missing_texts)
            for idx, text, vec in zip(missing_indices, missing_texts, api_vectors):
                results[idx] = vec
                if self._cache is not None:
                    try:
                        self._cache.set(text, model, vec)
                    except Exception as e:
                        logger.warning(f"EmbeddingCache set failed for doc index {idx} (fail-open): {e}")

        return results  # type: ignore

    def __getattr__(self, name: str) -> Any:
        return getattr(self._embedder, name)

