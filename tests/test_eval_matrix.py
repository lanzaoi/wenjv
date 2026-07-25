import os
import csv
import pytest
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_eval_matrix_run(m_format, m_search, m_load, tmp_path):
    from eval.run_matrix import run_matrix, CONFIGS
    
    # 1. Mock load_sample returning 2 queries
    m_load.return_value = [
        {"qid": "q1", "query": "hello world", "relevant_pids": ["p100"]},
        {"qid": "q2", "query": "test msmarco", "relevant_pids": ["p200"]},
    ]
    
    # 2. Mock search_documents returning empty list
    m_search.return_value = []
    m_format.return_value = ([], "empty stats")
    
    csv_file = str(tmp_path / "ab_matrix.csv")
    md_file = str(tmp_path / "ab_matrix.md")
    out_dir_base = str(tmp_path / "results")
    
    summaries = await run_matrix(
        limit=2,
        out_dir_base=out_dir_base,
        csv_output=csv_file,
        md_output=md_file
    )
        
    assert len(summaries) == 4
    for s in summaries:
        assert s["n_queries"] == 2
        assert s["n_no_hits"] == 2  # since search_documents returned empty
        assert s["MRR@10"] == 0.0
        assert "runtime_sec" in s
        assert s["status"] == "SUCCESS"
        
    # Verify CSV structure and 4 rows
    assert os.path.exists(csv_file)
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 4
        assert set(row["config"] for row in reader) == set(CONFIGS)
        assert all(row["n_queries"] == "2" for row in reader)
        
    # Verify Markdown table has all 4 rows
    assert os.path.exists(md_file)
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()
        for cfg in CONFIGS:
            assert f"`{cfg}`" in content


@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_eval_matrix_error_isolation(m_format, m_search, m_load, tmp_path):
    from eval.run_matrix import run_matrix
    
    m_load.return_value = [{"qid": "q1", "query": "test", "relevant_pids": ["p1"]}]
    
    # Make search_documents raise an exception when config is 'rerank_on'
    async def side_effect(*args, **kwargs):
        from backend.config import settings
        if settings.RERANK_ENABLED:
            raise RuntimeError("Simulated Rerank OOM error")
        return []
        
    m_search.side_effect = side_effect
    m_format.return_value = ([], "stats")
    
    csv_file = str(tmp_path / "ab_matrix_err.csv")
    md_file = str(tmp_path / "ab_matrix_err.md")
    out_dir_base = str(tmp_path / "results_err")
    
    summaries = await run_matrix(
        limit=1,
        out_dir_base=out_dir_base,
        csv_output=csv_file,
        md_output=md_file
    )
    
    assert len(summaries) == 4
    rerank_s = next(s for s in summaries if s["config"] == "rerank_on")
    assert rerank_s["status"] == "FAILED"
    assert "Simulated Rerank OOM error" in rerank_s["error"]
    
    default_s = next(s for s in summaries if s["config"] == "default")
    assert default_s["status"] == "SUCCESS"
    
    # Verify CSV was written and has FAILED status row
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 4
        rerank_row = next(r for r in reader if r["config"] == "rerank_on")
        assert rerank_row["status"] == "FAILED"
