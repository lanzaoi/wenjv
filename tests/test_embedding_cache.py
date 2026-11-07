import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from datetime import datetime, timezone, timedelta
from langchain.schema import Document

from backend.config import settings
from backend.core.embedding_cache import EmbeddingCache, CachedEmbedder
from backend.api.services.search import _get_query_cache, _set_query_cache, _compute_query_hash
from backend.database import get_cache_engine, EmbedCacheTable, QueryResultCacheTable
from sqlalchemy.orm import Session
from sqlalchemy import delete


@pytest.fixture(autouse=True)
def setup_caching_test(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "QUERY_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "QUERY_CACHE_TTL_SECONDS", 300)
    
    # Ensure cache tables exist before cleaning
    EmbedCacheTable.__table__.create(bind=get_cache_engine(), checkfirst=True)
    QueryResultCacheTable.__table__.create(bind=get_cache_engine(), checkfirst=True)

    # Clean cache tables before each test
    with Session(get_cache_engine()) as session:
        session.execute(delete(EmbedCacheTable))
        session.execute(delete(QueryResultCacheTable))
        session.commit()


def test_hash_determinism():
    """测试 hash() 确定性（相同文本 -> 相同 hash）"""
    h1 = EmbeddingCache.hash("artificial intelligence knowledge base")
    h2 = EmbeddingCache.hash("artificial intelligence knowledge base")
    h3 = EmbeddingCache.hash("different text")
    
    assert len(h1) == 16
    assert isinstance(h1, str)
    assert h1 == h2
    assert h1 != h3


def test_get_set_roundtrip_and_model_isolation():
    """测试 get/set 往返与 model 隔离（不同 model 不同缓存）"""
    cache = EmbeddingCache()
    vec_a = [0.1, -0.5, 0.99]
    
    # get/set roundtrip
    cache.set("doc_content", "bge-m3", vec_a)
    cached_vec = cache.get("doc_content", "bge-m3")
    assert cached_vec is not None
    assert np.allclose(cached_vec, vec_a)
    
    # model isolation
    assert cache.get("doc_content", "text-embedding-3-large") is None
    
    # Different text under same model misses
    assert cache.get("other_content", "bge-m3") is None


def test_clear():
    """测试 clear() 清空指定模型与全表清空"""
    cache = EmbeddingCache()
    cache.set("text1", "model1", [1.0, 2.0])
    cache.set("text2", "model2", [3.0, 4.0])
    
    # Clear only model1
    cache.clear(model="model1")
    assert cache.get("text1", "model1") is None
    assert cache.get("text2", "model2") is not None
    
    # Clear entire table
    cache.clear()
    assert cache.get("text2", "model2") is None


def test_fail_open():
    """测试 fail-open（模拟 SQLite 异常，确认不阻断调用）"""
    mock_api = MagicMock()
    mock_api.model = "test_model"
    mock_api.embed_query.return_value = [0.5, 0.5]
    mock_api.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]
    
    mock_cache = MagicMock()
    mock_cache.get.side_effect = Exception("SQLite read failure")
    mock_cache.set.side_effect = Exception("SQLite write failure")
    
    embedder = CachedEmbedder(mock_api, cache=mock_cache)
    
    # embed_query should log warning and return API vector without raising exception
    res_query = embedder.embed_query("test query")
    assert res_query == [0.5, 0.5]
    mock_api.embed_query.assert_called_once_with("test query")
    
    # embed_documents should log warning and return API vectors without raising exception
    res_docs = embedder.embed_documents(["doc1", "doc2"])
    assert res_docs == [[0.1, 0.2], [0.3, 0.4]]
    mock_api.embed_documents.assert_called_once_with(["doc1", "doc2"])


def test_eval_bypass_mode(monkeypatch):
    """测试 eval bypass 模式（EMBEDDING_CACHE_ENABLED=false -> 不读写）"""
    cache = EmbeddingCache()
    
    # Turn OFF embedding cache (eval bypass)
    monkeypatch.setattr(settings, "EMBEDDING_CACHE_ENABLED", False)
    
    cache.set("eval_query", "model_eval", [0.8, 0.8])
    
    # Re-enable briefly to check if it was written
    monkeypatch.setattr(settings, "EMBEDDING_CACHE_ENABLED", True)
    assert cache.get("eval_query", "model_eval") is None
    
    # Write while enabled, then turn OFF and verify get() returns None
    cache.set("eval_query", "model_eval", [0.8, 0.8])
    assert cache.get("eval_query", "model_eval") is not None
    
    monkeypatch.setattr(settings, "EMBEDDING_CACHE_ENABLED", False)
    assert cache.get("eval_query", "model_eval") is None
    
    # Also verify CachedEmbedder bypasses cache
    mock_api = MagicMock()
    mock_api.embed_query.return_value = [1.0, 1.0]
    embedder = CachedEmbedder(mock_api, cache=cache)
    
    assert embedder.embed_query("eval_query") == [1.0, 1.0]
    mock_api.embed_query.assert_called_once_with("eval_query")


def test_query_result_cache_ttl(monkeypatch):
    """测试 query result cache TTL 过期"""
    q_hash = _compute_query_hash("test ttl", None, None, None, 2)
    doc = Document(page_content="TTL test doc", metadata={"id": "doc_1"})
    results = [(doc, 0.88)]
    
    with patch("backend.api.services.search.vector_store", None):
        # 1. Normal TTL (300s) -> hit
        monkeypatch.setattr(settings, "QUERY_CACHE_TTL_SECONDS", 300)
        _set_query_cache(q_hash, user_id=1, results=results)
        cached = _get_query_cache(q_hash, user_id=1)
        assert cached is not None
        assert cached[0][0].page_content == "TTL test doc"
        
        # 2. Expired TTL -> simulate by setting negative TTL when caching new item
        q_hash_expired = _compute_query_hash("expired query", None, None, None, 2)
        monkeypatch.setattr(settings, "QUERY_CACHE_TTL_SECONDS", -10)
        _set_query_cache(q_hash_expired, user_id=1, results=results)
        
        # Restore normal TTL for reading, but entry expires_at is already in the past
        monkeypatch.setattr(settings, "QUERY_CACHE_TTL_SECONDS", 300)
        expired_cached = _get_query_cache(q_hash_expired, user_id=1)
        assert expired_cached is None


def test_query_cache_tenant_isolation():
    """测试 query cache 租户隔离（User A 写入的缓存，User B 相同 query 不命中）"""
    q_hash = _compute_query_hash("sensitive financial report 2026", None, None, None, 5)
    doc_user_a = Document(page_content="User A Private Salary: $500,000", metadata={"tenant": "A"})
    results_a = [(doc_user_a, 0.99)]
    
    with patch("backend.api.services.search.vector_store", None):
        # User A (user_id=100) searches and caches result
        _set_query_cache(q_hash, user_id=100, results=results_a)
        
        # User A hits cache
        cached_a = _get_query_cache(q_hash, user_id=100)
        assert cached_a is not None
        assert len(cached_a) == 1
        assert "500,000" in cached_a[0][0].page_content
        
        # User B (user_id=200) executes exact same search -> MUST MISS CACHE
        cached_b = _get_query_cache(q_hash, user_id=200)
        assert cached_b is None
