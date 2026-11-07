import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from backend.api.services.chat import rag_chat_events
from backend.config import settings

@pytest.mark.asyncio
async def test_rag_refuse_on_empty(monkeypatch):
    """Test that when RAG_REFUSE_ON_EMPTY is true, empty retrieval triggers a refusal and avoids LLM call."""
    monkeypatch.setattr(settings, "RAG_REFUSE_ON_EMPTY", True)
    
    with patch('backend.api.services.chat.search_service.search_documents') as m_search:
        # Mock empty hits
        m_search.return_value = []
        
        # We also want to mock the LLM streaming just in case it tries to call it, 
        # so we can assert it was NOT called.
        with patch('backend.api.services.chat.stream_openai_chat') as m_openai:
            with patch('backend.api.services.chat.stream_ollama_chat') as m_ollama:
                
                gen = rag_chat_events(
                    question='test',
                    user_email='test@example.com',
                    user_id=1,
                    use_rag=True
                )
                
                events = [e async for e in gen]
                
                # Check events
                # 1. Citations should be empty
                assert events[0] == {"type": "citations", "citations": []}
                # 2. Token should be the refusal message
                assert events[1] == {"type": "token", "content": "抱歉，知识库中未找到相关依据，无法回答该问题。"}
                # 3. Done
                assert events[2] == {"type": "done"}
                
                # Assert that the LLM was never called
                m_openai.assert_not_called()
                m_ollama.assert_not_called()

@pytest.mark.asyncio
async def test_rag_does_not_refuse_if_turned_off(monkeypatch):
    """Test that if RAG_REFUSE_ON_EMPTY is false, it proceeds to call the LLM."""
    monkeypatch.setattr(settings, "RAG_REFUSE_ON_EMPTY", False)
    
    with patch('backend.api.services.chat.search_service.search_documents') as m_search:
        m_search.return_value = []
        
        # Mock LLM stream generator
        async def mock_stream(*args, **kwargs):
            yield "Hello"
            
        with patch('backend.api.services.chat.stream_ollama_chat', side_effect=mock_stream) as m_ollama:
            with patch('backend.api.services.chat.stream_openai_chat', side_effect=mock_stream) as m_openai:
                
                gen = rag_chat_events(
                    question='test',
                    user_email='test@example.com',
                    user_id=1,
                    use_rag=True
                )
                
                events = [e async for e in gen]
                
                assert events[0] == {"type": "citations", "citations": []}
                # Token from the mock stream
                assert events[1] == {"type": "token", "content": "Hello"}
                assert events[2] == {"type": "done"}
                
                # LLM should have been called
                if getattr(settings, "CHAT_PROVIDER", "ollama").lower() == "ollama":
                    m_ollama.assert_called_once()
                else:
                    m_openai.assert_called_once()

