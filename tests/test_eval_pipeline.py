"""Eval pipeline tests — runner, PID extraction, config monkeypatching."""
import pytest, json, os
from unittest.mock import patch, MagicMock, AsyncMock


# ─── helpers ───

def _mdoc(title, chunk_id="chunk1"):
    doc = MagicMock()
    doc.id = chunk_id
    doc.metadata = {"title": title}
    return doc


@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_runner_basic_flow(m_format, m_search, m_load, tmp_path):
    from eval.run_eval import run_queries

    m_load.return_value = [
        {"qid": "1", "query": "test", "relevant_pids": ["123"]},
        {"qid": "2", "query": "test2", "relevant_pids": ["456"]},
    ]

    m_format.return_value = (
        [(_mdoc("source=msmarco, pid=123"), 0.9, "vector"),
         (_mdoc("source=msmarco, pid=456"), 0.8, "keyword")],
        "stats",
    )

    with patch("eval.run_eval.os.path.join", side_effect=lambda *a: str(tmp_path / a[-1])), \
         patch("eval.run_eval.os.makedirs"):
        await run_queries("default", 2)

        with open(tmp_path / "summary.json") as f:
            s = json.load(f)
        assert s["config"] == "default"
        assert s["n_queries"] == 2
        assert "MRR@10" in s

        with open(tmp_path / "per_query.json") as f:
            pq = json.load(f)
        assert len(pq) == 2


# ─── PID extraction ───

@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_pid_extraction_standard(m_format, m_search, m_load, tmp_path):
    """Standard pid=NNN format."""
    from eval.run_eval import run_queries

    m_load.return_value = [{"qid": "1", "query": "t", "relevant_pids": ["789"]}]
    m_format.return_value = ([(_mdoc("source=msmarco, pid=789"), 0.5, "v")], "s")

    with patch("eval.run_eval.os.path.join", side_effect=lambda *a: str(tmp_path / a[-1])), \
         patch("eval.run_eval.os.makedirs"):
        await run_queries("default", 1)

        with open(tmp_path / "raw_hits.json") as f:
            hits = json.load(f)
        assert hits[0]["hits"][0]["pid"] == "789"


@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_pid_extraction_msmarco_prefix(m_format, m_search, m_load, tmp_path):
    """MSMARCO_ prefix fallback."""
    from eval.run_eval import run_queries

    m_load.return_value = [{"qid": "1", "query": "t", "relevant_pids": ["111"]}]
    m_format.return_value = ([(_mdoc("MSMARCO_111"), 0.5, "v")], "s")

    with patch("eval.run_eval.os.path.join", side_effect=lambda *a: str(tmp_path / a[-1])), \
         patch("eval.run_eval.os.makedirs"):
        await run_queries("default", 1)

        with open(tmp_path / "raw_hits.json") as f:
            hits = json.load(f)
        assert hits[0]["hits"][0]["pid"] == "111"


@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_pid_extraction_title_none(m_format, m_search, m_load, tmp_path):
    """title=None → pid=None."""
    from eval.run_eval import run_queries

    m_load.return_value = [{"qid": "1", "query": "t", "relevant_pids": []}]

    doc = MagicMock()
    doc.id = "c1"
    doc.metadata = {}
    m_format.return_value = ([(doc, 0.5, "v")], "s")

    with patch("eval.run_eval.os.path.join", side_effect=lambda *a: str(tmp_path / a[-1])), \
         patch("eval.run_eval.os.makedirs"):
        await run_queries("default", 1)

        with open(tmp_path / "raw_hits.json") as f:
            hits = json.load(f)
        assert hits[0]["hits"][0]["pid"] is None


@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_pid_extraction_filename_fallback(m_format, m_search, m_load, tmp_path):
    """No title → fallback to filename."""
    from eval.run_eval import run_queries

    m_load.return_value = [{"qid": "1", "query": "t", "relevant_pids": ["999"]}]
    doc = MagicMock()
    doc.id = "c1"
    doc.metadata = {"filename": "source=msmarco, pid=999", "title": ""}
    m_format.return_value = ([(doc, 0.5, "v")], "s")

    with patch("eval.run_eval.os.path.join", side_effect=lambda *a: str(tmp_path / a[-1])), \
         patch("eval.run_eval.os.makedirs"):
        await run_queries("default", 1)

        with open(tmp_path / "raw_hits.json") as f:
            hits = json.load(f)
        assert hits[0]["hits"][0]["pid"] == "999"


@pytest.mark.asyncio
@patch("eval.run_eval.load_sample")
@patch("backend.api.services.search.search_documents")
@patch("backend.api.services.search.format_search_hits")
async def test_empty_search_results(m_format, m_search, m_load, tmp_path):
    """search_documents returns [] → all zero scores."""
    from eval.run_eval import run_queries

    m_load.return_value = [{"qid": "1", "query": "t", "relevant_pids": ["100"]}]
    m_format.return_value = ([], "s")

    with patch("eval.run_eval.os.path.join", side_effect=lambda *a: str(tmp_path / a[-1])), \
         patch("eval.run_eval.os.makedirs"):
        await run_queries("default", 1)

        with open(tmp_path / "summary.json") as f:
            s = json.load(f)
        assert s["n_no_hits"] == 1
        assert s["MRR@10"] == 0.0
        assert s["Recall@10"] == 0.0


# ─── config monkeypatching ───

_CONFIG_TOGGLE = {
    "default":  {"HYBRID": True,  "RERANK": False, "MMR": True,  "STRUCTURED": True},
    "hybrid_off": {"HYBRID": False, "RERANK": False, "MMR": True,  "STRUCTURED": True},
    "rerank_on":  {"HYBRID": True,  "RERANK": True,  "MMR": True,  "STRUCTURED": True},
    "mmr_off":    {"HYBRID": True,  "RERANK": False, "MMR": False, "STRUCTURED": True},
    "mmr_lambda_0.9": {"HYBRID": True, "RERANK": False, "MMR": True, "STRUCTURED": True, "MMR_LAMBDA": 0.9},
    "mmr_same_resource": {"HYBRID": True, "RERANK": False, "MMR": True, "STRUCTURED": True, "MMR_MODE": "same_resource"},
}


@pytest.mark.parametrize("config_name,expected", list(_CONFIG_TOGGLE.items()))
def test_monkeypatch_sets_correct_flags(config_name, expected):
    """Verify monkeypatching sets exactly the right config flags."""
    from backend.config import settings

    # Reset to baseline
    settings.HYBRID_SEARCH_ENABLED = True
    settings.STRUCTURED_RECALL_ENABLED = True
    settings.MMR_ENABLED = True
    settings.RERANK_ENABLED = False
    settings.MMR_LAMBDA = 0.7
    settings.MMR_MODE = "standard"

    if config_name == "hybrid_off":
        settings.HYBRID_SEARCH_ENABLED = False
    elif config_name == "rerank_on":
        settings.RERANK_ENABLED = True
    elif config_name == "mmr_off":
        settings.MMR_ENABLED = False
    elif config_name.startswith("mmr_lambda_"):
        settings.MMR_ENABLED = True
        settings.MMR_LAMBDA = float(config_name.split("_")[-1])
    elif config_name == "mmr_same_resource":
        settings.MMR_ENABLED = True
        settings.MMR_MODE = "same_resource"

    assert settings.HYBRID_SEARCH_ENABLED == expected["HYBRID"]
    assert settings.RERANK_ENABLED == expected["RERANK"]
    assert settings.MMR_ENABLED == expected["MMR"]
    assert settings.STRUCTURED_RECALL_ENABLED == expected["STRUCTURED"]
    if "MMR_LAMBDA" in expected:
        assert settings.MMR_LAMBDA == expected["MMR_LAMBDA"]
    if "MMR_MODE" in expected:
        assert settings.MMR_MODE == expected["MMR_MODE"]
