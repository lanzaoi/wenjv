import pytest
from unittest.mock import patch
from backend.config import settings
from backend.api.services.search import search_documents
from langchain.schema import Document

def _mock_doc(content, id_str):
    return Document(page_content=content, metadata={"id": id_str})

@pytest.fixture(autouse=True)
def reset_settings():
    settings.HYBRID_SEARCH_ENABLED = True
    settings.HYBRID_KEYWORD_BACKEND = "fts5"
    settings.STRUCTURED_RECALL_ENABLED = True
    settings.HYBRID_RRF_K = 5
    settings.HYBRID_RRF_WEIGHT_VECTOR = 1.0
    settings.HYBRID_RRF_WEIGHT_KEYWORD = 1.0
    settings.HYBRID_RRF_WEIGHT_STRUCTURED = 1.0
    settings.RERANK_ENABLED = False
    settings.MMR_ENABLED = False
    yield

@pytest.mark.asyncio
async def test_search_structured_hit():
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5', return_value=[]), \
         patch('backend.api.services.search.search_resources') as m_struct_res, \
         patch('backend.api.services.search.fetch_documents_by_resource') as m_fetch:
         
        # Vector returns v1
        m_store.fetch_documents.return_value = [
            (_mock_doc("v1", "v1"), 0.1),
        ]
        
        # Structured returns s1
        m_struct_res.return_value = [{"resource_id": 99, "source_type": "note"}]
        m_fetch.return_value = [(_mock_doc("s1", "s1"), 0.0)]
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1)
        
        # Both should be in RRF
        assert len(results) == 2
        ids = [r[0].metadata["id"] for r in results]
        assert "v1" in ids
        assert "s1" in ids
        
        m_struct_res.assert_called_once()
        m_fetch.assert_called_once()

@pytest.mark.asyncio
async def test_search_structured_disabled():
    settings.STRUCTURED_RECALL_ENABLED = False
    
    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5', return_value=[]), \
         patch('backend.api.services.search.search_resources') as m_struct_res:
         
        # Vector returns v1
        m_store.fetch_documents.return_value = [
            (_mock_doc("v1", "v1"), 0.1),
        ]
        
        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1)
        
        # Structured should be totally skipped
        m_struct_res.assert_not_called()
        assert len(results) == 1
        assert results[0][0].metadata["id"] == "v1"
