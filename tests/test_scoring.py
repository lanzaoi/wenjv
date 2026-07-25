import pytest
from eval.scoring import score_hits, summarize

def test_score_hits_rank_1():
    hits = [
        {"pid": "100", "rank": 1},
        {"pid": "200", "rank": 2},
    ]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 1.0
    assert res["hit_at_5"] is True
    assert res["hit_at_10"] is True
    assert res["recall_at_5"] == 1.0
    assert res["recall_at_10"] == 1.0

def test_score_hits_rank_3():
    hits = [
        {"pid": "101", "rank": 1},
        {"pid": "102", "rank": 2},
        {"pid": "100", "rank": 3},
    ]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert abs(res["reciprocal_rank"] - 1.0 / 3.0) < 1e-6
    assert res["hit_at_5"] is True
    assert res["hit_at_10"] is True
    assert res["recall_at_5"] == 1.0
    assert res["recall_at_10"] == 1.0

def test_score_hits_no_hit():
    hits = [
        {"pid": "101", "rank": 1},
        {"pid": "102", "rank": 2},
    ]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 0.0
    assert res["hit_at_5"] is False
    assert res["hit_at_10"] is False
    assert res["recall_at_5"] == 0.0
    assert res["recall_at_10"] == 0.0

def test_score_hits_recall_counts():
    # Suppose 4 relevant documents total
    rel = {"10", "20", "30", "40"}
    hits = [
        {"pid": "10", "rank": 2},   # hit in top 5
        {"pid": "20", "rank": 4},   # hit in top 5
        {"pid": "99", "rank": 5},
        {"pid": "30", "rank": 8},   # hit in top 10 (not in top 5)
        {"pid": "40", "rank": 15},  # hit outside top 10
    ]
    res = score_hits(hits, rel)
    assert res["reciprocal_rank"] == 0.5  # first hit at rank 2
    assert res["recall_at_5"] == 2 / 4.0   # pid 10, 20
    assert res["recall_at_10"] == 3 / 4.0  # pid 10, 20, 30
    assert res["n_rel_retrieved"] == 4

def test_summarize():
    scores = [
        # Query 1: MRR=1.0, R@5=1.0, R@10=1.0
        {"reciprocal_rank": 1.0, "recall_at_5": 1.0, "recall_at_10": 1.0, "hit_at_10": True},
        # Query 2: MRR=0.5, R@5=0.5, R@10=0.5
        {"reciprocal_rank": 0.5, "recall_at_5": 0.5, "recall_at_10": 0.5, "hit_at_10": True},
        # Query 3: MRR=0.0, R@5=0.0, R@10=0.0 (no hit)
        {"reciprocal_rank": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0, "hit_at_10": False},
        # Query 4: MRR=0.0, R@5=0.0, R@10=0.0 (no hit)
        {"reciprocal_rank": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0, "hit_at_10": False},
    ]
    summary = summarize(scores)
    assert summary["n_queries"] == 4
    assert summary["n_no_hits"] == 2
    assert abs(summary["MRR@10"] - (1.5 / 4.0)) < 1e-6
    assert abs(summary["Recall@5"] - (1.5 / 4.0)) < 1e-6
    assert abs(summary["Recall@10"] - (1.5 / 4.0)) < 1e-6

def test_score_hits_pid_none():
    hits = [
        {"pid": None, "rank": 1},
        {"pid": "None", "rank": 2},
        {"pid": "100", "rank": 3},
    ]
    rel = {"100"}
    res = score_hits(hits, rel)
    assert abs(res["reciprocal_rank"] - 1.0 / 3.0) < 1e-6
    assert res["hit_at_5"] is True
    assert res["recall_at_5"] == 1.0

def test_score_hits_dynamic_k():
    hits = [
        {"pid": "100", "rank": 15},
    ]
    rel = {"100"}
    res = score_hits(hits, rel, k_values=(5, 10, 20))
    assert res["hit_at_5"] is False
    assert res["hit_at_10"] is False
    assert res["hit_at_20"] is True
    assert res["recall_at_20"] == 1.0

