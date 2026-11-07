"""Test suite for rule-based Query Classifier and Dynamic RRF Weighting (v1.4 T3)."""
import pytest
from unittest.mock import patch
from langchain_core.documents import Document

from backend.core.query_classifier import classify
from backend.config import settings
from backend.api.services.search import search_documents


def test_short_keyword_classification():
    """Test short keyword classification (<= 10 chars or alphanumeric model patterns)."""
    assert classify("Python") == "short_keyword"
    assert classify("性能优化") == "short_keyword"
    assert classify("RTX4090") == "short_keyword"
    assert classify("i7-13700K") == "short_keyword"


def test_long_question_classification():
    """Test long question classification (contains question words and > 8 chars)."""
    assert classify("个人知识库的向量检索和关键词检索怎么融合比较好") == "long_question"
    assert classify("为什么向量数据库在高并发场景下查询延时会抖动呢") == "long_question"


def test_default_classification():
    """Test default classification (not short, no model pattern, no question word)."""
    assert classify("个人知识库的向量检索机制和实现架构") == "default"
    assert classify("大规模分布式集群的部署方案实践指南") == "default"


def test_model_pattern_recognition_long_text():
    """Test model pattern recognition in texts > 10 characters without question words."""
    assert classify("RTX4090显卡规格说明和性能架构深度剖析说明") == "short_keyword"
    assert classify("iPhone15ProMax设计参数说明文档") == "short_keyword"


def test_chinese_question_words_recognition():
    """Test recognition of all primary Chinese question words in > 8 char sentences."""
    words = ["什么", "怎么", "为什么", "如何", "哪", "吗", "呢", "吧"]
    for word in words:
        query = f"这里的配置应该{word}修改比较合理"
        assert classify(query) == "long_question", f"Failed for question word: {word}"


def test_priority_conflict():
    """Test priority conflict when query matches both model pattern and question word."""
    # 'RTX4090是什么' length is 10 > 8, contains '什么' (long_question) and 'RTX4090' (short_keyword).
    # Should prioritize long_question.
    assert classify("RTX4090是什么") == "long_question"
    assert classify("iPhone15Pro如何配置深度学习环境呢") == "long_question"


def test_edge_cases():
    """Test edge cases: empty string, pure punctuation, whitespace, super long text."""
    assert classify("") == "default"
    assert classify("   ") == "short_keyword"  # stripped length 0 <= 10 without question words -> short_keyword
    assert classify("！！！") == "short_keyword"  # <= 10 chars without question words -> short_keyword
    assert classify("一二三四五六七八九十十一十二") == "default"  # > 10 chars, no q words, no models -> default


def _mock_doc(doc_id: str, content: str) -> Document:
    return Document(page_content=content, metadata={"id": doc_id, "source_type": "upload"})


@pytest.fixture
def mock_search_env(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "HYBRID_KEYWORD_BACKEND", "fts5")
    monkeypatch.setattr(settings, "HYBRID_RRF_K", 5)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_VECTOR", 1.0)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_KEYWORD", 1.0)
    monkeypatch.setattr(settings, "HYBRID_RRF_WEIGHT_STRUCTURED", 0.0)
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    monkeypatch.setattr(settings, "STRUCTURED_RECALL_ENABLED", False)


@pytest.mark.asyncio
async def test_dynamic_rrf_weight_calculation_and_cap(mock_search_env, monkeypatch):
    """Test dynamic RRF weight boosting and max weight cap in search pipeline."""
    # We configure initial w_v=1.0, w_k=1.0.
    # For short keyword ('Python'), boost=10.0, max_w=4.0 -> w_k capped at 4.0.
    # RRF score for k1 = 4.0 / (5 + 1) = 2/3. In search_documents, return distance is 1.0 / rrf_score = 1.5.
    # RRF score for v1 = 1.0 / (5 + 1) = 1/6. Distance is 6.0.
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_ENABLED", True)
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_SHORT_BOOST", 10.0)
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_SHORT_KEYWORD_BOOST", 10.0)
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_MAX_WEIGHT", 4.0)

    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5') as m_fts5, \
         patch('backend.api.services.search.obs_logger'):

        # Vector returns doc v1 at rank 1
        m_store.fetch_documents.return_value = [(_mock_doc("v1", "vector content"), 0.1)]
        # FTS5 returns doc k1 at rank 1
        m_fts5.return_value = [{"chunk_id": "k1", "page_content": "keyword content"}]

        results = await search_documents(prompt="Python", user_email="test@test.com", user_id=1)

        assert len(results) == 2
        assert results[0][0].metadata["id"] == "k1"
        assert abs(results[0][1] - 1.5) < 1e-6
        assert results[1][0].metadata["id"] == "v1"
        assert abs(results[1][1] - 6.0) < 1e-6


@pytest.mark.asyncio
async def test_dynamic_rrf_weight_long_question_boost(mock_search_env, monkeypatch):
    """Test dynamic RRF weight boosting for long questions."""
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_ENABLED", True)
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_LONG_BOOST", 10.0)
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_LONG_QUESTION_BOOST", 10.0)
    monkeypatch.setattr(settings, "QUERY_CLASSIFIER_MAX_WEIGHT", 4.0)

    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.fts5_utils.match_fts5') as m_fts5, \
         patch('backend.api.services.search.obs_logger'):

        m_store.fetch_documents.return_value = [(_mock_doc("v1", "vector content"), 0.1)]
        m_fts5.return_value = [{"chunk_id": "k1", "page_content": "keyword content"}]

        prompt = "个人知识库的向量检索和关键词检索怎么融合比较好"
        results = await search_documents(prompt=prompt, user_email="test@test.com", user_id=1)

        assert len(results) == 2
        # w_v becomes 4.0 (capped), w_k remains 1.0. Thus v1 ranks before k1.
        assert results[0][0].metadata["id"] == "v1"
        assert abs(results[0][1] - 1.5) < 1e-6
        assert results[1][0].metadata["id"] == "k1"
        assert abs(results[1][1] - 6.0) < 1e-6
