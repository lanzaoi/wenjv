import pytest
from unittest.mock import patch, AsyncMock
from backend.config import settings
from backend.api.services.search import search_documents
from langchain.schema import Document

def _mock_doc(content, id_str):
    return Document(page_content=content, metadata={"id": id_str})

@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    # Reset settings before each test
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", False)
    monkeypatch.setattr(settings, "HYBRID_KEYWORD_BACKEND", "fts5")
    monkeypatch.setattr(settings, "HYBRID_VECTOR_MAX_DISTANCE", 0.8)
    monkeypatch.setattr(settings, "HYBRID_RRF_K", 5)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_VECTOR", 1.0)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_KEYWORD", 1.0)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_STRUCTURED", 1.0)
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    monkeypatch.setattr(settings, "STRUCTURED_RECALL_ENABLED", False)

@pytest.mark.asyncio
async def test_hybrid_off_vector_only(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", False)
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5') as m_fts5:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("v1", "v1"), 0.1),
        ]
        
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1)
        
        assert len(results) == 1
        m_fts5.assert_not_called()
        m_store.fetch_documents_keyword.assert_not_called()

@pytest.mark.asyncio
async def test_empty_keyword_returns_vector(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "HYBRID_KEYWORD_BACKEND", "fts5")
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5', return_value=[]) as m_fts5:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("v1", "v1"), 0.1),
        ]
        
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1)
        
        assert len(results) == 1
        assert results[0][0].metadata["id"] == "v1"
        assert results[0][1] == 0.1  # Native vector distance is returned

@pytest.mark.asyncio
async def test_backend_like(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "HYBRID_KEYWORD_BACKEND", "like")
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5') as m_fts5:
        
        m_store.fetch_documents.return_value = [(_mock_doc("v1", "v1"), 0.1)]
        m_store.fetch_documents_keyword.return_value = [(_mock_doc("k1", "k1"), 0.0)]
        
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1)
        
        assert len(results) == 2
        m_fts5.assert_not_called()
        m_store.fetch_documents_keyword.assert_called_once()

@pytest.mark.asyncio
async def test_hybrid_vector_distance_filter(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "HYBRID_KEYWORD_BACKEND", "fts5")
    monkeypatch.setattr(settings, "HYBRID_VECTOR_MAX_DISTANCE", 0.8)
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5') as m_fts5:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("v1", "v1"), 0.1),
            (_mock_doc("v2", "v2"), 0.9),  # Should be filtered out by distance
        ]
        # k1 returned by fts5
        m_fts5.return_value = [{"chunk_id": "k1", "page_content": "k1"}]
        
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1)
        
        assert len(results) == 2
        ids = [r[0].metadata["id"] for r in results]
        assert "v1" in ids
        assert "k1" in ids
        assert "v2" not in ids

@pytest.mark.asyncio
async def test_weighted_rrf_vector_weight_dominates(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "HYBRID_KEYWORD_BACKEND", "fts5")
    monkeypatch.setattr(settings, "HYBRID_RRF_K", 5)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_VECTOR", 1.0)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_KEYWORD", 0.1)  # Small weight
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5') as m_fts5:
        
        m_store.fetch_documents.return_value = [(_mock_doc("v1", "v1"), 0.1)]
        m_fts5.return_value = [{"chunk_id": "k1", "page_content": "k1"}]
        
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1)
        
        assert len(results) == 2
        assert results[0][0].metadata["id"] == "v1"
        assert results[1][0].metadata["id"] == "k1"

@pytest.mark.asyncio
async def test_mmr_integration(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "MMR_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_CANDIDATES", 10)
    monkeypatch.setattr(settings, "MMR_LAMBDA", 0.5)
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5', return_value=[]), \
         patch('backend.core.mmr.mmr_diversify') as m_mmr:
        
        # mock embed_query and embed_documents
        class MockEmbeddings:
            def embed_query(self, text): return [1, 0]
            def embed_documents(self, texts): return [[1, 0], [1, 0], [0, 1]]
        
        m_store.embeddings = MockEmbeddings()
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("sim1", "v1"), 0.1),
            (_mock_doc("sim2", "v2"), 0.2),
            (_mock_doc("div1", "v3"), 0.3),
        ]
        
        # MMR mock should return v1 and v3
        m_mmr.return_value = [
            (_mock_doc("sim1", "v1"), 0.1),
            (_mock_doc("div1", "v3"), 0.3),
        ]
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1, window_size=2)
        
        # MMR should be called because fetch_limit > window_size (10 > 2) and MMR is enabled
        m_mmr.assert_called_once()
        assert len(results) == 2
        assert results[0][0].metadata["id"] == "v1"
        assert results[1][0].metadata["id"] == "v3"

@pytest.mark.asyncio
async def test_rerank_integration(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", False)
    monkeypatch.setattr(settings, "MMR_ENABLED", False)
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_CANDIDATES", 10)
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.rerank_client.rerank', new_callable=AsyncMock) as m_rerank:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("v1", "v1"), 0.1),
            (_mock_doc("v2", "v2"), 0.2),
        ]
        
        m_rerank.return_value = [
            {"index": 1, "relevance_score": 0.99},
            {"index": 0, "relevance_score": 0.50},
        ]
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1, window_size=2)
        
        m_rerank.assert_called_once_with("test", ["v1", "v2"])
        assert len(results) == 2
        assert results[0][0].metadata["id"] == "v2"
        assert results[1][0].metadata["id"] == "v1"

