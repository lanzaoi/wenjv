import pytest
import asyncio
from unittest.mock import patch, MagicMock
from backend.api.services.search import search_documents
from backend.config import settings

@pytest.mark.asyncio
async def test_search_parallel_legs_success():
    """Test that when SEARCH_PARALLEL_LEGS is True, the search gathers all results without errors."""
    original = getattr(settings, "SEARCH_PARALLEL_LEGS", True)
    original_hybrid = getattr(settings, "HYBRID_SEARCH_ENABLED", False)
    settings.SEARCH_PARALLEL_LEGS = True
    settings.HYBRID_SEARCH_ENABLED = True
    
    try:
        with patch("backend.api.services.search.vector_store.fetch_documents") as mock_vector:
            mock_vector.return_value = []
            with patch("backend.core.fts5_utils.match_fts5", return_value=[]) as mock_fts5:
                # We expect the search to run without error and the functions to be called
                results = await search_documents(
                    prompt="test query",
                    user_email="test@example.com"
                )
                assert isinstance(results, list)
    finally:
        settings.SEARCH_PARALLEL_LEGS = original
        settings.HYBRID_SEARCH_ENABLED = original_hybrid

@pytest.mark.asyncio
async def test_search_parallel_legs_fail_open():
    """Test that if a single parallel leg fails, it fails open and does not crash search_documents."""
    original = getattr(settings, "SEARCH_PARALLEL_LEGS", True)
    original_hybrid = getattr(settings, "HYBRID_SEARCH_ENABLED", False)
    settings.SEARCH_PARALLEL_LEGS = True
    settings.HYBRID_SEARCH_ENABLED = True
    
    try:
        with patch("backend.api.services.search.vector_store.fetch_documents") as mock_vector:
            mock_vector.return_value = []
            with patch("backend.core.fts5_utils.match_fts5", side_effect=Exception("FTS5 failed")):
                # The search should succeed because keyword leg failing should not drag down the search
                results = await search_documents(
                    prompt="test fail open query",
                    user_email="test@example.com"
                )
                assert isinstance(results, list)
    finally:
        settings.SEARCH_PARALLEL_LEGS = original
        settings.HYBRID_SEARCH_ENABLED = original_hybrid
