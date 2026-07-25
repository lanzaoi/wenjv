import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from backend.core.rerank_client import rerank
from backend.config import settings
import httpx

@pytest.fixture(autouse=True)
def setup_settings():
    settings.RERANK_ENABLED = True
    settings.RERANK_PROVIDER = "siliconflow"
    settings.RERANK_API_BASE = "https://api.siliconflow.cn/v1"
    settings.RERANK_API_KEY = "test_key"
    settings.EMBEDDING_API_KEY = "test_key_emb"
    settings.RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
    settings.RERANK_TIMEOUT_SECONDS = 8
    yield

@pytest.mark.asyncio
async def test_rerank_success():
    # Mock httpx.AsyncClient.post
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.9, "document": {"text": "doc2"}},
            {"index": 0, "relevance_score": 0.1, "document": {"text": "doc1"}}
        ]
    }
    
    mock_post_func = AsyncMock(return_value=mock_response)
    with patch('httpx.AsyncClient.post', new=mock_post_func) as mock_post:
        results = await rerank("query", ["doc1", "doc2"])
        
        assert len(results) == 2
        assert results[0]["index"] == 1
        assert results[0]["relevance_score"] == 0.9
        
        # Verify post arguments
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["query"] == "query"
        assert kwargs["json"]["documents"] == ["doc1", "doc2"]
        assert kwargs["json"]["model"] == "BAAI/bge-reranker-v2-m3"
        assert kwargs["headers"]["Authorization"] == "Bearer test_key"
        assert kwargs["timeout"] == 8

@pytest.mark.asyncio
async def test_rerank_fallback_api_key():
    settings.RERANK_API_KEY = ""
    settings.EMBEDDING_API_KEY = "test_key_emb"
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    
    mock_post_func = AsyncMock(return_value=mock_response)
    with patch('httpx.AsyncClient.post', new=mock_post_func) as mock_post:
        results = await rerank("query", ["doc1"])
        
        # Should use EMBEDDING_API_KEY when RERANK_API_KEY is empty
        args, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test_key_emb"

@pytest.mark.asyncio
async def test_rerank_fallback_api_base():
    settings.RERANK_API_BASE = ""
    settings.EMBEDDING_API_BASE = "https://custom.embed.api/v1"
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    
    mock_post_func = AsyncMock(return_value=mock_response)
    with patch('httpx.AsyncClient.post', new=mock_post_func) as mock_post:
        results = await rerank("query", ["doc1"])
        
        # Should use EMBEDDING_API_BASE
        args, kwargs = mock_post.call_args
        assert args[0] == "https://custom.embed.api/v1/rerank"

@pytest.mark.asyncio
async def test_rerank_empty_key_fails_open():
    settings.RERANK_API_KEY = ""
    settings.EMBEDDING_API_KEY = ""
    
    mock_post_func = AsyncMock()
    with patch('httpx.AsyncClient.post', new=mock_post_func) as mock_post:
        results = await rerank("query", ["doc1"])
        
        # Should return empty list and not call API
        assert results == []
        mock_post.assert_not_called()

@pytest.mark.asyncio
async def test_rerank_timeout_fails_open():
    mock_post_func = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    with patch('httpx.AsyncClient.post', new=mock_post_func):
        results = await rerank("query", ["doc1"])
        assert results == []

@pytest.mark.asyncio
async def test_rerank_http_error_fails_open():
    mock_post_func = AsyncMock(side_effect=httpx.HTTPError("Error"))
    with patch('httpx.AsyncClient.post', new=mock_post_func):
        results = await rerank("query", ["doc1"])
        assert results == []

@pytest.mark.asyncio
async def test_rerank_empty_documents():
    results = await rerank("query", [])
    assert results == []
