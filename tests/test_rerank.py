"""Tests for rerank_client — fail-open architecture.

Failures return None (not []) so callers can distinguish
"API down" from "no relevant documents."
"""
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
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.9, "document": {"text": "doc2"}},
            {"index": 0, "relevance_score": 0.1, "document": {"text": "doc1"}},
        ]
    }

    mock_post_func = AsyncMock(return_value=mock_response)
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        results = await rerank("query", ["doc1", "doc2"])

        assert results is not None
        assert len(results) == 2
        assert results[0]["index"] == 1
        assert results[0]["relevance_score"] == 0.9

        args, kwargs = mock_post_func.call_args
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
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        await rerank("query", ["doc1"])
        args, kwargs = mock_post_func.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test_key_emb"


@pytest.mark.asyncio
async def test_rerank_embeddings_base_stripped():
    """RERANK_API_BASE empty, EMBEDDING_API_BASE has /embeddings suffix → stripped."""
    settings.RERANK_API_BASE = ""
    settings.EMBEDDING_API_BASE = "https://api.siliconflow.cn/v1/embeddings"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}

    mock_post_func = AsyncMock(return_value=mock_response)
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        await rerank("query", ["doc1"])
        args, kwargs = mock_post_func.call_args
        assert args[0] == "https://api.siliconflow.cn/v1/rerank"


@pytest.mark.asyncio
async def test_rerank_no_key_returns_none():
    settings.RERANK_API_KEY = ""
    settings.EMBEDDING_API_KEY = ""

    mock_post_func = AsyncMock()
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        results = await rerank("query", ["doc1"])
        assert results is None
        mock_post_func.assert_not_called()


@pytest.mark.asyncio
async def test_rerank_disabled_returns_none():
    settings.RERANK_ENABLED = False

    mock_post_func = AsyncMock()
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        results = await rerank("query", ["doc1"])
        assert results is None
        mock_post_func.assert_not_called()


@pytest.mark.asyncio
async def test_rerank_empty_docs_returns_none():
    results = await rerank("query", [])
    assert results is None


@pytest.mark.asyncio
async def test_rerank_timeout_returns_none():
    mock_post_func = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        results = await rerank("query", ["doc1"])
        assert results is None


@pytest.mark.asyncio
async def test_rerank_http_error_returns_none():
    mock_post_func = AsyncMock(side_effect=httpx.HTTPError("Error"))
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        results = await rerank("query", ["doc1"])
        assert results is None


@pytest.mark.asyncio
async def test_rerank_404_returns_none():
    """Real-world: SF returns 404 for bad URL → None, caller preserves originals."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=MagicMock(), response=mock_response
    )
    mock_post_func = AsyncMock(return_value=mock_response)
    with patch("httpx.AsyncClient.post", new=mock_post_func):
        results = await rerank("query", ["doc1"])
        assert results is None


@pytest.mark.asyncio
async def test_rerank_local_onnx_success(monkeypatch):
    """Test Local BGE Reranker ONNX provider sorts relevant docs first."""
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "local_onnx")
    docs = [
        "知识库问据（wenjv）支持混合检索与重排序。",
        "今天天气晴朗适合出门跑步。",
    ]
    results = await rerank("知识库问据", docs)
    assert results is not None
    assert len(results) == 2
    assert results[0]["index"] == 0
    assert results[0]["relevance_score"] > results[1]["relevance_score"]
