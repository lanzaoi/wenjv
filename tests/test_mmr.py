"""Tests for backend.core.mmr — MMR diversity reranking."""
import numpy as np
import pytest
from backend.core.mmr import mmr_diversify, cosine_sim


def make_candidates(n: int, dim: int = 8):
    """Generate n random candidates for testing."""
    rng = np.random.RandomState(42)
    return [
        (f"id_{i}", rng.randn(dim).astype(np.float32), {"idx": i, "text": f"doc_{i}"})
        for i in range(n)
    ]


class TestCosineSim:
    def test_identical(self):
        v = np.array([1.0, 2.0, 3.0])
        assert cosine_sim(v, v) == pytest.approx(1.0)

    def test_orthogonal(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert cosine_sim(a, b) == pytest.approx(0.0)

    def test_zero_vector(self):
        assert cosine_sim(np.zeros(3), np.ones(3)) == 0.0
        assert cosine_sim(np.ones(3), np.zeros(3)) == 0.0


class TestMMRDiversify:
    def test_empty_candidates(self):
        result = mmr_diversify(np.ones(4), [], k=5)
        assert result == []

    def test_k_zero(self):
        candidates = make_candidates(10)
        result = mmr_diversify(np.ones(8), candidates, k=0)
        assert result == []

    def test_k_exceeds_n(self):
        """k > len(candidates): return all in original order."""
        candidates = make_candidates(3)
        result = mmr_diversify(np.ones(8), candidates, k=10)
        assert len(result) == 3

    def test_lambda_one_pure_relevance(self):
        """λ=1.0: pure relevance — first picked should be max cosine sim."""
        dim = 4
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        candidates = [
            ("a", np.array([0.1, 0.9, 0.0, 0.0], dtype=np.float32), {"n": "a"}),
            ("b", np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32), {"n": "b"}),
            ("c", np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32), {"n": "c"}),
        ]
        result = mmr_diversify(query, candidates, k=2, lambda_=1.0)
        # "b" has highest cosine sim to query → picked first
        assert result[0]["n"] == "b"

    def test_lambda_zero_pure_diversity(self):
        """λ=0.0: pure diversity — picks most dissimilar doc."""
        dim = 4
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        candidates = [
            ("a", np.array([0.99, 0.0, 0.0, 0.0], dtype=np.float32), {"n": "a"}),
            ("b", np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), {"n": "b"}),
            ("c", np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32), {"n": "c"}),
        ]
        result = mmr_diversify(query, candidates, k=3, lambda_=0.0)
        # "a" has highest relevance → picked first (tie-break = relevance)
        assert result[0]["n"] == "a"
        # Second pick: most dissimilar to "a" = "b" (orthogonal)
        assert result[1]["n"] == "b"

    def test_no_duplicates(self):
        """MMR should never return duplicates."""
        candidates = make_candidates(20)
        query = np.random.RandomState(7).randn(8).astype(np.float32)
        result = mmr_diversify(query, candidates, k=10, lambda_=0.7)
        idxs = [r["idx"] for r in result]
        assert len(idxs) == len(set(idxs))

    def test_degenerate_query_zero_vector(self):
        """Zero query vector → returns first k candidates."""
        candidates = make_candidates(10)
        result = mmr_diversify(np.zeros(8), candidates, k=5)
        assert len(result) == 5

    def test_default_lambda(self):
        """Default λ=0.7 should work without explicit argument."""
        candidates = make_candidates(5)
        result = mmr_diversify(np.ones(8), candidates, k=3)
        assert len(result) == 3
