import pytest
from unittest.mock import patch
from backend.api.services.search import search_documents
from backend.config import settings

@pytest.mark.asyncio
async def test_search_timing_enabled_success():
    """Test that when SEARCH_TIMING_ENABLED is True, search still succeeds and logs timings."""
    original = getattr(settings, "SEARCH_TIMING_ENABLED", False)
    settings.SEARCH_TIMING_ENABLED = True
    
    try:
        with patch("backend.api.services.search.logger.info") as mock_logger_info:
            # We mock the vector store to avoid actual DB hits, or we just rely on the fallback
            with patch("backend.api.services.search.vector_store.fetch_documents") as mock_fetch:
                mock_fetch.return_value = []
                
                results = await search_documents(
                    prompt="test query",
                    user_email="test@example.com"
                )
                
                assert isinstance(results, list)
                
                # Verify logger was called with timings
                called_with_timings = False
                for call in mock_logger_info.mock_calls:
                    if "search_timings" in str(call.args[0]):
                        called_with_timings = True
                        break
                assert called_with_timings, "Expected logger.info to be called with search_timings"
    finally:
        settings.SEARCH_TIMING_ENABLED = original

@pytest.mark.asyncio
async def test_search_timing_fail_open():
    """Test that if logging timings throws an error, search still returns correctly."""
    original = getattr(settings, "SEARCH_TIMING_ENABLED", False)
    settings.SEARCH_TIMING_ENABLED = True
    
    try:
        # Mock logger.info to raise an exception
        with patch("backend.api.services.search.logger.info", side_effect=Exception("Logger failed")):
            with patch("backend.api.services.search.vector_store.fetch_documents") as mock_fetch:
                mock_fetch.return_value = []
                
                # Should not raise
                results = await search_documents(
                    prompt="test query",
                    user_email="test@example.com"
                )
                
                assert isinstance(results, list)
    finally:
        settings.SEARCH_TIMING_ENABLED = original
