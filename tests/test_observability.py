import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import delete

from backend.database import sync_engine, QueryLogsTable
from backend.core.observability import ObsLogger


@pytest.fixture(autouse=True)
def setup_obs_test():
    QueryLogsTable.__table__.create(bind=sync_engine, checkfirst=True)
    with Session(sync_engine) as session:
        session.execute(delete(QueryLogsTable))
        session.commit()
    yield


def test_obs_logger_log_and_get_recent():
    obs = ObsLogger()
    
    obs.log(
        query="what is RAG?",
        latency_ms=120.5,
        v_hits=5,
        fts5_hits=2,
        s_hits=0,
        total_hits=7,
        cache_hit=False,
        error=None,
    )
    
    obs.log(
        query="cached question",
        latency_ms=5.0,
        v_hits=0,
        fts5_hits=0,
        s_hits=0,
        total_hits=3,
        cache_hit=True,
        error=None,
    )
    
    recent = obs.get_recent(limit=10)
    assert len(recent) == 2
    # Most recent should be "cached question"
    assert recent[0]["query"] == "cached question"
    assert recent[0]["cache_hit"] is True
    assert recent[0]["latency_ms"] == 5.0
    
    assert recent[1]["query"] == "what is RAG?"
    assert recent[1]["cache_hit"] is False
    assert recent[1]["v_hits"] == 5


def test_obs_logger_get_stats():
    obs = ObsLogger()
    
    # Empty stats
    stats_empty = obs.get_stats()
    assert stats_empty["total_queries"] == 0
    assert stats_empty["avg_latency_ms"] == 0.0
    assert stats_empty["v_hit_rate"] == 0.0
    
    # Add 4 queries:
    # 1. v hit, fts5 hit, not cache, not error (100ms)
    obs.log("q1", 100.0, 3, 2, 0, 5, False, None)
    # 2. s hit, cache hit, not error (10ms)
    obs.log("q2", 10.0, 0, 0, 1, 1, True, None)
    # 3. v hit, cache hit, not error (20ms)
    obs.log("q3", 20.0, 1, 0, 0, 1, True, None)
    # 4. error query (200ms)
    obs.log("q4", 200.0, 0, 0, 0, 0, False, "TimeoutError")
    
    stats = obs.get_stats()
    assert stats["total_queries"] == 4
    # avg latency: (100+10+20+200)/4 = 330/4 = 82.5
    assert stats["avg_latency_ms"] == 82.5
    # v_hit_rate: 2/4 = 0.5
    assert stats["v_hit_rate"] == 0.5
    # fts5_hit_rate: 1/4 = 0.25
    assert stats["fts5_hit_rate"] == 0.25
    # s_hit_rate: 1/4 = 0.25
    assert stats["s_hit_rate"] == 0.25
    # cache_hit_rate: 2/4 = 0.5
    assert stats["cache_hit_rate"] == 0.5
    # error_rate: 1/4 = 0.25
    assert stats["error_rate"] == 0.25
    # last_24h_queries: 4
    assert stats["last_24h_queries"] == 4


def test_obs_logger_fail_open():
    mock_engine = MagicMock()
    # Execute raises exception
    mock_engine.connect.side_effect = Exception("DB offline")
    
    obs = ObsLogger(engine=mock_engine)
    # log should catch exception and not raise
    obs.log("fail test", 10.0, 0, 0, 0, 0, False, None)
    
    # get_recent should catch exception and return empty list
    assert obs.get_recent() == []
    
    # get_stats should catch exception and return default zeroes
    stats = obs.get_stats()
    assert stats["total_queries"] == 0


@pytest.mark.asyncio
async def test_search_documents_observability(monkeypatch):
    from backend.api.services.search import search_documents, obs_logger, vector_store
    from langchain.schema import Document
    from backend.database import QueryResultCacheTable, get_cache_engine
    import time as _time
    
    # Ensure clean query result cache table on cache engine
    cache_eng = get_cache_engine()
    QueryResultCacheTable.__table__.create(bind=cache_eng, checkfirst=True)
    with Session(cache_eng) as session:
        session.execute(delete(QueryResultCacheTable))
        session.commit()
    
    # Mock vector_store.fetch_documents to return 2 docs
    def mock_fetch(*args, **kwargs):
        return [
            (Document(page_content="doc 1", metadata={"id": "doc1"}), 0.1),
            (Document(page_content="doc 2", metadata={"id": "doc2"}), 0.2),
        ]
    
    monkeypatch.setattr(vector_store, "fetch_documents", mock_fetch)
    
    test_q = f"obs test query {_time.time()}"
    # 1. First search (cache miss)
    res = await search_documents(prompt=test_q, user_email="user@test.com")
    assert len(res) == 2
    
    recent = obs_logger.get_recent(limit=5)
    assert len(recent) >= 1
    top_log = recent[0]
    assert top_log["query"] == test_q
    assert top_log["cache_hit"] is False
    assert top_log["v_hits"] == 2
    assert top_log["total_hits"] == 2
    assert top_log["error"] is None
    
    # 2. Second search (cache hit)
    res2 = await search_documents(prompt=test_q, user_email="user@test.com")
    assert len(res2) == 2
    
    recent2 = obs_logger.get_recent(limit=5)
    assert len(recent2) >= 2
    top_log2 = recent2[0] # most recent
    assert top_log2["query"] == test_q
    assert top_log2["cache_hit"] is True
    assert top_log2["total_hits"] == 2
    assert top_log2["error"] is None
    
    # 3. Third search with error
    def mock_fetch_err(*args, **kwargs):
        raise ValueError("simulated vector crash")
    
    monkeypatch.setattr(vector_store, "fetch_documents", mock_fetch_err)
    
    with pytest.raises(ValueError, match="simulated vector crash"):
        await search_documents(prompt="error query", user_email="user@test.com")
        
    recent3 = obs_logger.get_recent(limit=5)
    top_log3 = recent3[0]
    assert top_log3["query"] == "error query"
    assert top_log3["cache_hit"] is False
    assert top_log3["error"] == "simulated vector crash"


def test_admin_endpoints_when_enabled():
    from fastapi.testclient import TestClient
    from backend.main import app
    
    client = TestClient(app)
    
    # 1. Test GET /admin/stats
    resp_stats = client.get("/admin/stats")
    assert resp_stats.status_code == 200
    data = resp_stats.json()
    assert "total_queries" in data
    assert "avg_latency_ms" in data
    assert "cache_hit_rate" in data
    
    # 2. Test GET /admin HTML page
    resp_html = client.get("/admin")
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers.get("content-type", "")
    assert "此页面无需认证，请勿将 API 端口暴露至公网" in resp_html.text
    assert '<meta http-equiv="refresh" content="30">' in resp_html.text
    assert "总查询数" in resp_html.text
    
    # 3. Test GET /admin/ trailing slash
    resp_html_slash = client.get("/admin/")
    assert resp_html_slash.status_code == 200
    assert "此页面无需认证，请勿将 API 端口暴露至公网" in resp_html_slash.text


def test_admin_endpoints_when_disabled(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.config import settings
    
    monkeypatch.setattr(settings, "ADMIN_ENABLED", False)
    client = TestClient(app)
    
    resp_stats = client.get("/admin/stats")
    assert resp_stats.status_code == 404
    assert resp_stats.json()["detail"] == "Admin interface is disabled"
    resp_html = client.get("/admin")
    assert resp_html.status_code == 404


def test_active_alert_engine(caplog, monkeypatch):
    import logging
    from backend.core.observability import ObsLogger
    from backend.config import settings
    
    monkeypatch.setattr(settings, "OBS_ALERT_FTS5_ZERO_HIT_STREAK", 3)
    monkeypatch.setattr(settings, "OBS_ALERT_LATENCY_STREAK", 2)
    monkeypatch.setattr(settings, "OBS_ALERT_LATENCY_THRESHOLD_MS", 500.0)
    monkeypatch.setattr(settings, "OBS_ALERT_ERROR_STREAK", 2)
    monkeypatch.setattr(settings, "OBS_ALERT_COOLDOWN_SECONDS", 1000)  # long cooldown
    
    obs = ObsLogger()
    obs.reset_alert_streaks()
    
    with caplog.at_level(logging.ERROR):
        # 1. Test FTS5 zero hit streak
        obs.log("q1", 10.0, 1, 0, 0, 1, False)  # streak 1
        assert "ALERT: FTS5 zero-hit streak" not in caplog.text
        obs.log("q2", 10.0, 1, 0, 0, 1, False)  # streak 2
        assert "ALERT: FTS5 zero-hit streak" not in caplog.text
        obs.log("q3", 10.0, 1, 0, 0, 1, False)  # streak 3 -> ALERT!
        assert "ALERT: FTS5 zero-hit streak >= 3" in caplog.text
        
        # Test cooldown: next query shouldn't emit another alert
        caplog.clear()
        obs.log("q4", 10.0, 1, 0, 0, 1, False)  # streak 4
        assert "ALERT: FTS5 zero-hit streak" not in caplog.text
        
        # Test streak reset
        obs.log("q5", 10.0, 1, 1, 0, 2, False)  # fts5_hits = 1 -> resets streak!
        assert obs.fts5_zero_hit_streak == 0
        
        # 2. Test Latency streak
        caplog.clear()
        obs.reset_alert_streaks()
        obs.log("lat1", 600.0, 1, 1, 0, 1, False)  # streak 1
        assert "ALERT: Latency streak" not in caplog.text
        obs.log("lat2", 600.0, 1, 1, 0, 1, False)  # streak 2 -> ALERT!
        assert "ALERT: Latency streak >= 2" in caplog.text
        
        # Test latency streak reset
        obs.log("lat3", 100.0, 1, 1, 0, 1, False)  # latency <= 500
        assert obs.latency_streak == 0
        
        # 3. Test Error streak
        caplog.clear()
        obs.reset_alert_streaks()
        obs.log("err1", 10.0, 0, 0, 0, 0, False, error="err1")  # streak 1
        assert "ALERT: Error streak" not in caplog.text
        obs.log("err2", 10.0, 0, 0, 0, 0, False, error="err2")  # streak 2 -> ALERT!
        assert "ALERT: Error streak >= 2" in caplog.text
        
        # Test error streak reset
        obs.log("err3", 10.0, 1, 1, 0, 1, False, error=None)
        assert obs.error_streak == 0


def test_api_call_counters(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.config import settings
    from backend.core.observability import ObsLogger, increment_api_count
    
    monkeypatch.setattr(settings, "ADMIN_ENABLED", True)
    client = TestClient(app)
    obs = ObsLogger()
    
    # 1. Reset counts to clean state
    obs.reset_api_counts()
    
    # 2. Increment counters
    increment_api_count("siliconflow", "embed", 2)
    increment_api_count("siliconflow", "rerank", 1)
    
    counts = { (item["provider"], item["call_type"]): item["call_count"] for item in obs.get_api_counts() }
    assert counts.get(("siliconflow", "embed")) == 2
    assert counts.get(("siliconflow", "rerank")) == 1
    
    # 3. Check admin page rendering
    resp_html = client.get("/admin")
    assert resp_html.status_code == 200
    assert "API 调用计数器" in resp_html.text
    assert "siliconflow" in resp_html.text
    assert "rerank" in resp_html.text
    
    # 4. Test manual reset endpoint
    resp_reset = client.post("/admin/reset-counts")
    assert resp_reset.status_code == 200
    assert resp_reset.json()["message"] == "API call counts reset successfully"
    
    # 5. Verify counts reset to 0
    counts_after = { (item["provider"], item["call_type"]): item["call_count"] for item in obs.get_api_counts() }
    for val in counts_after.values():
        assert val == 0


def test_fts5_zero_hit_alert_10_streak(caplog, monkeypatch):
    import logging
    from backend.core.observability import ObsLogger
    from backend.config import settings
    
    monkeypatch.setattr(settings, "OBS_ALERT_FTS5_ZERO_HIT_STREAK", 10)
    monkeypatch.setattr(settings, "OBS_ALERT_FTS5_ZERO_HIT_THRESHOLD", 10)
    monkeypatch.setattr(settings, "OBS_ALERT_COOLDOWN_SECONDS", 300)
    
    obs = ObsLogger()
    obs.reset_alert_streaks()
    
    with caplog.at_level(logging.ERROR):
        for i in range(9):
            obs.log(f"q_{i}", 10.0, 1, 0, 0, 1, False)
        assert "ALERT: FTS5 zero-hit streak" not in caplog.text
        
        # 10th zero hit should trigger alert
        obs.log("q_9", 10.0, 1, 0, 0, 1, False)
        assert "ALERT: FTS5 zero-hit streak >= 10" in caplog.text





