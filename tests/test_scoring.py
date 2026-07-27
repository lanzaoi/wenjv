"""Comprehensive scoring tests — every metric, every edge case."""
import pytest
from eval.scoring import score_hits, summarize


# ─── score_hits: basic correctness ───

def test_rank_1_hit():
    hits = [{"pid": "100", "rank": 1}, {"pid": "200", "rank": 2}]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 1.0
    assert res["hit_at_5"] is True
    assert res["hit_at_10"] is True
    assert res["recall_at_5"] == 1.0
    assert res["recall_at_10"] == 1.0
    assert res["n_rel_retrieved"] == 1
    assert res["n_rel_total"] == 1


def test_rank_3_hit():
    hits = [{"pid": "101", "rank": 1}, {"pid": "102", "rank": 2}, {"pid": "100", "rank": 3}]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert abs(res["reciprocal_rank"] - 1.0 / 3.0) < 1e-6
    assert res["hit_at_5"] is True
    assert res["hit_at_10"] is True


def test_no_hit():
    hits = [{"pid": "101", "rank": 1}, {"pid": "102", "rank": 2}]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 0.0
    assert res["hit_at_5"] is False
    assert res["hit_at_10"] is False
    assert res["recall_at_5"] == 0.0
    assert res["recall_at_10"] == 0.0
    assert res["n_rel_retrieved"] == 0


def test_first_relevant_beyond_k():
    """MRR@10 = 0 when first relevant is at rank 12 (> max_k=10)."""
    hits = [{"pid": str(i), "rank": i} for i in range(1, 15)]
    rel = {"13"}  # at rank 13
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 0.0  # first relevant beyond k=10
    assert res["hit_at_10"] is False
    assert res["n_rel_retrieved"] == 1  # still counted globally


def test_all_hits_match():
    hits = [{"pid": "1", "rank": 1}, {"pid": "2", "rank": 2}]
    rel = {"1", "2"}
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 1.0
    assert res["recall_at_5"] == 1.0
    assert res["recall_at_10"] == 1.0
    assert res["n_rel_retrieved"] == 2


def test_partial_recall():
    """4 relevant total, only 2 in hits."""
    rel = {"10", "20", "30", "40"}
    hits = [
        {"pid": "10", "rank": 2},
        {"pid": "20", "rank": 4},
        {"pid": "99", "rank": 5},
        {"pid": "30", "rank": 8},
        {"pid": "40", "rank": 15},
    ]
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 0.5  # first at rank 2
    assert res["recall_at_5"] == 2 / 4.0  # 10,20 in top 5
    assert res["recall_at_10"] == 3 / 4.0  # 10,20,30 in top 10
    assert res["n_rel_retrieved"] == 4  # all 4 found somewhere


# ─── score_hits: edge cases ───

def test_empty_hits():
    res = score_hits([], {"100"})
    assert res["reciprocal_rank"] == 0.0
    assert res["hit_at_5"] is False
    assert res["hit_at_10"] is False
    assert res["recall_at_5"] == 0.0
    assert res["recall_at_10"] == 0.0
    assert res["n_rel_retrieved"] == 0
    assert res["n_rel_total"] == 1


def test_empty_relevant_pids():
    res = score_hits([{"pid": "100", "rank": 1}], set())
    assert res["reciprocal_rank"] == 0.0
    assert res["n_rel_total"] == 0
    # When relevant_pids is empty, we hit early-return without computing metrics
    assert res["hit_at_5"] is False
    assert res["recall_at_5"] == 0.0


def test_no_rank_key():
    """Hits without 'rank' key fall back to enumerate order (1-indexed)."""
    hits = [
        {"pid": "a"},  # no rank → rank=1
        {"pid": "b"},  # → rank=2
        {"pid": "c"},  # → rank=3
    ]
    rel = {"c"}
    res = score_hits(hits, rel)
    assert abs(res["reciprocal_rank"] - 1.0 / 3.0) < 1e-6


def test_some_ranks_missing():
    hits = [
        {"pid": "a", "rank": 10},
        {"pid": "b"},  # no rank → sort key=9999 (placed last), enumerate gives rank=3
        {"pid": "c", "rank": 1},
    ]
    # sorted by rank: c(1), a(10), b(sort=9999, enumerate rank=3)
    rel = {"b"}
    res = score_hits(hits, rel)
    assert abs(res["reciprocal_rank"] - 1.0 / 3.0) < 1e-6  # b at rank 3


def test_duplicate_pids_in_hits():
    """Same pid appearing twice → counted once (dedup)."""
    hits = [
        {"pid": "100", "rank": 1},
        {"pid": "100", "rank": 5},  # duplicate
    ]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert res["n_rel_retrieved"] == 1  # not 2
    assert res["reciprocal_rank"] == 1.0  # first at rank 1


def test_pid_none_and_string_none():
    hits = [
        {"pid": None, "rank": 1},
        {"pid": "None", "rank": 2},  # string "None" should be ignored
        {"pid": "100", "rank": 3},
    ]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert abs(res["reciprocal_rank"] - 1.0 / 3.0) < 1e-6
    assert res["hit_at_5"] is True
    assert res["hit_at_10"] is True


def test_pid_empty_string():
    hits = [
        {"pid": "", "rank": 1},
        {"pid": "   ", "rank": 2},
        {"pid": "100", "rank": 3},
    ]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert abs(res["reciprocal_rank"] - 1.0 / 3.0) < 1e-6


def test_pid_integer():
    """pid passed as int should be converted to str for set membership."""
    hits = [{"pid": 100, "rank": 1}]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 1.0


def test_dynamic_k_values():
    hits = [{"pid": "100", "rank": 15}]
    rel = {"100"}
    res = score_hits(hits, rel, k_values=(5, 10, 20))
    assert res["hit_at_5"] is False
    assert res["hit_at_10"] is False
    assert res["hit_at_20"] is True
    assert res["recall_at_5"] == 0.0
    assert res["recall_at_10"] == 0.0
    assert res["recall_at_20"] == 1.0


def test_single_k_value():
    hits = [{"pid": "100", "rank": 3}]
    rel = {"100"}
    res = score_hits(hits, rel, k_values=(5,))
    assert "hit_at_5" in res
    assert "hit_at_10" not in res
    assert res["hit_at_5"] is True
    assert res["recall_at_5"] == 1.0


# ─── summarize: edge cases ───

def test_summarize_basic():
    scores = [
        {"reciprocal_rank": 1.0, "recall_at_5": 1.0, "recall_at_10": 1.0, "hit_at_10": True},
        {"reciprocal_rank": 0.5, "recall_at_5": 0.5, "recall_at_10": 0.5, "hit_at_10": True},
        {"reciprocal_rank": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0, "hit_at_10": False},
        {"reciprocal_rank": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0, "hit_at_10": False},
    ]
    s = summarize(scores)
    assert s["n_queries"] == 4
    assert s["n_no_hits"] == 2
    assert abs(s["MRR@10"] - 1.5 / 4.0) < 1e-6
    assert abs(s["Recall@5"] - 1.5 / 4.0) < 1e-6
    assert abs(s["Recall@10"] - 1.5 / 4.0) < 1e-6


def test_summarize_all_perfect():
    scores = [
        {"reciprocal_rank": 1.0, "recall_at_5": 1.0, "recall_at_10": 1.0, "hit_at_10": True},
        {"reciprocal_rank": 1.0, "recall_at_5": 1.0, "recall_at_10": 1.0, "hit_at_10": True},
    ]
    s = summarize(scores)
    assert s["n_queries"] == 2
    assert s["n_no_hits"] == 0
    assert s["MRR@10"] == 1.0
    assert s["Recall@5"] == 1.0
    assert s["Recall@10"] == 1.0


def test_summarize_all_zero():
    scores = [
        {"reciprocal_rank": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0, "hit_at_10": False},
        {"reciprocal_rank": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0, "hit_at_10": False},
    ]
    s = summarize(scores)
    assert s["n_queries"] == 2
    assert s["n_no_hits"] == 2
    assert s["MRR@10"] == 0.0
    assert s["Recall@5"] == 0.0
    assert s["Recall@10"] == 0.0


def test_summarize_empty():
    s = summarize([])
    assert s["n_queries"] == 0
    assert s["MRR@10"] == 0.0
    assert s["Recall@5"] == 0.0


def test_summarize_single_query():
    scores = [{"reciprocal_rank": 0.25, "recall_at_5": 0.5, "recall_at_10": 1.0, "hit_at_10": True}]
    s = summarize(scores)
    assert s["n_queries"] == 1
    assert s["n_no_hits"] == 0
    assert s["MRR@10"] == 0.25


def test_summarize_custom_k_values():
    scores = [
        {"reciprocal_rank": 0.5, "recall_at_5": 0.0, "recall_at_10": 1.0, "recall_at_20": 1.0, "hit_at_20": True},
    ]
    s = summarize(scores, k_values=(5, 10, 20))
    assert s["n_queries"] == 1
    assert s["MRR@20"] == 0.5
    assert s["Recall@5"] == 0.0
    assert s["Recall@10"] == 1.0
    assert s["Recall@20"] == 1.0
    assert s["n_no_hits"] == 0  # hit_at_20=True


# ─── bootstrap_ci ───

def test_bootstrap_ci_empty():
    from eval.scoring import bootstrap_ci
    result = bootstrap_ci([], metric="reciprocal_rank")
    assert result["mean"] == 0.0
    assert result["n"] == 0


def test_bootstrap_ci_basic():
    from eval.scoring import bootstrap_ci
    scores = [
        {"reciprocal_rank": 1.0},
        {"reciprocal_rank": 0.5},
        {"reciprocal_rank": 0.0},
    ]
    result = bootstrap_ci(scores, metric="reciprocal_rank")
    assert "mean" in result
    assert "ci_95_lower" in result
    assert "ci_95_upper" in result
    assert result["n"] == 3
    # CI should contain the mean
    assert result["ci_95_lower"] <= result["mean"] <= result["ci_95_upper"]


def test_bootstrap_ci_all_same():
    from eval.scoring import bootstrap_ci
    scores = [{"reciprocal_rank": 0.5}] * 100
    result = bootstrap_ci(scores, metric="reciprocal_rank")
    # All same → CI should be tight
    assert abs(result["ci_95_upper"] - result["ci_95_lower"]) < 0.01


def test_summarize_includes_bootstrap_ci():
    from eval.scoring import summarize
    scores = [{"reciprocal_rank": 1.0, "recall_at_5": 1.0, "recall_at_10": 1.0, "hit_at_10": True}]
    s = summarize(scores)
    assert "MRR@10_ci95" in s
