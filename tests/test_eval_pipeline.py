import pytest
import os
import json
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
@patch('eval.run_eval.load_sample')
@patch('backend.api.services.search.search_documents')
@patch('backend.api.services.search.format_search_hits')
async def test_eval_pipeline_runner(m_format, m_search, m_load, tmp_path):
    from eval.run_eval import run_queries
    
    # Mock load_sample
    m_load.return_value = [
        {"qid": "1", "query": "test query 1"},
        {"qid": "2", "query": "test query 2"},
    ]
    
    # Mock format_search_hits to return 2 dummy hits
    m_doc1 = MagicMock()
    m_doc1.id = "chunk1"
    m_doc1.metadata = {"title": "source=msmarco, pid=123"}
    
    m_doc2 = MagicMock()
    m_doc2.id = "chunk2"
    m_doc2.metadata = {"title": "source=msmarco, pid=456"}
    
    m_format.return_value = (
        [(m_doc1, 0.9, "vector"), (m_doc2, 0.8, "keyword")],
        "stats"
    )
    
    with patch('eval.run_eval.os.makedirs') as m_makedirs, \
         patch('eval.run_eval.open', new_callable=MagicMock) as m_open:
        
        m_file = MagicMock()
        m_open.return_value.__enter__.return_value = m_file
        
        await run_queries("default", 2)
        
        assert m_search.call_count == 2
        m_file.write.assert_called()

@pytest.mark.asyncio
@patch('eval.run_eval.load_sample')
@patch('backend.api.services.search.search_documents')
@patch('backend.api.services.search.format_search_hits')
async def test_eval_pipeline_runner_output(m_format, m_search, m_load, tmp_path):
    from eval.run_eval import run_queries
    
    m_load.return_value = [
        {"qid": "1", "query": "test query 1"},
    ]
    
    m_doc1 = MagicMock()
    m_doc1.id = "chunk1"
    m_doc1.metadata = {"title": "source=msmarco, pid=123"}
    
    m_format.return_value = (
        [(m_doc1, 0.9, "vector")],
        "stats"
    )
    
    with patch('eval.run_eval.os.path.join', side_effect=lambda *args: str(tmp_path / args[-1])), \
         patch('eval.run_eval.os.makedirs'):
        
        await run_queries("hybrid_off", 1)
        
        with open(tmp_path / "raw_hits.json", "r", encoding="utf-8") as f:
            results = json.load(f)
            
        assert len(results) == 1
        assert results[0]["qid"] == "1"
        assert len(results[0]["hits"]) == 1
        assert results[0]["hits"][0]["pid"] == "123"
        assert results[0]["hits"][0]["rank"] == 1
        assert results[0]["hits"][0]["chunk_id"] == "chunk1"
        
        with open(tmp_path / "summary.json", "r", encoding="utf-8") as f:
            summary = json.load(f)
        assert summary["config"] == "hybrid_off"
        assert "MRR@10" in summary
        assert "Recall@5" in summary
        
        with open(tmp_path / "per_query.json", "r", encoding="utf-8") as f:
            per_query = json.load(f)
        assert len(per_query) == 1
        assert per_query[0]["qid"] == "1"

