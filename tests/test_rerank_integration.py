import pytest
from unittest.mock import patch, AsyncMock
from backend.config import settings
from backend.api.services.search import search_documents
from langchain.schema import Document

def _mock_doc(content, id_str):
    return Document(page_content=content, metadata={"id": id_str})

@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", False)
    monkeypatch.setattr(settings, "MMR_ENABLED", False)
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_CANDIDATES", 10)

@pytest.mark.asyncio
async def test_search_rerank_enabled():
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.rerank_client.rerank', new_callable=AsyncMock) as m_rerank:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("doc_v1", "v1"), 0.1),
            (_mock_doc("doc_v2", "v2"), 0.2),
        ]
        
        m_rerank.return_value = [
            {"index": 1, "relevance_score": 0.99},
            {"index": 0, "relevance_score": 0.50},
        ]
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1, window_size=2)
        
        m_rerank.assert_called_once_with("test", ["doc_v1", "doc_v2"])
        assert len(results) == 2
        assert results[0][0].metadata["id"] == "v2"
        assert results[1][0].metadata["id"] == "v1"

@pytest.mark.asyncio
async def test_search_rerank_disabled(monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.rerank_client.rerank', new_callable=AsyncMock) as m_rerank:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("doc_v1", "v1"), 0.1),
            (_mock_doc("doc_v2", "v2"), 0.2),
        ]
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1, window_size=2)
        
        m_rerank.assert_not_called()
        assert len(results) == 2
        assert results[0][0].metadata["id"] == "v1"
        assert results[1][0].metadata["id"] == "v2"

@pytest.mark.asyncio
async def test_search_rerank_fail_open_preserves_order():
    """When rerank returns None (API failure), results stay in original RRF order."""
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.rerank_client.rerank', new_callable=AsyncMock) as m_rerank:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("doc_v1", "v1"), 0.1),
            (_mock_doc("doc_v2", "v2"), 0.2),
        ]
        
        # Simulate API failure → None (new fail-open contract)
        m_rerank.return_value = None
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1, window_size=2)
        
        m_rerank.assert_called_once_with("test", ["doc_v1", "doc_v2"])
        # Must preserve original RRF order (v1 before v2)
        assert len(results) == 2
        assert results[0][0].metadata["id"] == "v1"
        assert results[1][0].metadata["id"] == "v2"


@pytest.mark.asyncio
async def test_search_rerank_fail_open_empty_results():
    """When rerank returns empty list, results stay in original RRF order."""
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.rerank_client.rerank', new_callable=AsyncMock) as m_rerank:
        
        m_store.fetch_documents.return_value = [
            (_mock_doc("doc_v1", "v1"), 0.1),
        ]
        
        # Empty results (API returned no scores — rare but possible)
        m_rerank.return_value = []
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1, window_size=1)
        
        # Must preserve original results
        assert len(results) == 1
        assert results[0][0].metadata["id"] == "v1"

