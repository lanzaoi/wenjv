"""
Maximal Marginal Relevance (MMR) — diversity-preserving reranking.

Mature reference: LangChain `langchain_community.vectorstores.utils.maximal_marginal_relevance`
Paper: Carbonell & Goldstein (1998), "The Use of MMR, Diversity-Based Reranking"

Formula: MMR = argmax_{d in R\\S} [ lambda*sim(d, Q) - (1-lambda)*max_{d' in S} sim(d, d') ]

Key design decisions (aligned with LangChain):
  - Both sim₁ (query-doc) and sim₂ (doc-doc) use cosine similarity
  - Greedy selection — standard tradeoff (optimal is NP-hard)
  - λ = 0.7 default — slight bias toward relevance over diversity
  - Applied post-retrieval (not full corpus) — candidate pool is typically ≤ 20
"""
from __future__ import annotations

import numpy as np


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors. Returns 0 if either is zero-norm."""
    a_norm = np.linalg.norm(a)
    b_norm = np.linalg.norm(b)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def mmr_diversify(
    query_vec: np.ndarray,
    candidates: list[tuple[str, np.ndarray, dict]],
    k: int,
    lambda_: float = 0.7,
) -> list[dict]:
    """
    Select up to k diverse, relevant items from candidates using MMR.

    Args:
        query_vec: embedding of the user query (shape: [dim])
        candidates: list of (id, embedding, payload) tuples
        k: maximum number of items to return
        lambda_: relevance-diversity tradeoff.
                  1.0 = pure relevance ordering
                  0.0 = pure diversity (max dissimilarity)

    Returns:
        list of payloads in MMR-selected order, length ≤ k

    Mature comparison:
      LangChain `maximal_marginal_relevance` uses identical formula and defaults.
      Pinecone/Weaviate/Elasticsearch offer built-in MMR with same semantics.
    """
    if not candidates or k <= 0:
        return []

    n = len(candidates)
    if k >= n:
        # No selection needed — return all in original order
        return [c[2] for c in candidates]

    # Pre-compute query-candidate similarities
    ids = [c[0] for c in candidates]
    vecs = np.stack([c[1] for c in candidates])  # [n, dim]
    payloads = [c[2] for c in candidates]

    # Cosine similarity between query and each candidate
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0:
        # Degenerate query — return first k
        return payloads[:k]

    query_sims = np.dot(vecs, query_vec) / (
        np.linalg.norm(vecs, axis=1) * q_norm + 1e-10
    )

    # Candidate-candidate similarity matrix (only computed lazily)
    # For MMR we only need sim to already-selected items, computed on demand
    selected_indices: list[int] = []
    remaining = set(range(n))

    # First selection: highest relevance (same as LangChain)
    first = int(np.argmax(query_sims))
    selected_indices.append(first)
    remaining.remove(first)

    # Greedy MMR for remaining k-1 slots
    while len(selected_indices) < k and remaining:
        best_idx = -1
        best_score = -float("inf")

        for i in remaining:
            relevance = query_sims[i]

            # Max similarity to any already-selected candidate
            max_redun = 0.0
            for j in selected_indices:
                sim = cosine_sim(vecs[i], vecs[j])
                max_redun = max(max_redun, sim)

            mmr_score = lambda_ * relevance - (1.0 - lambda_) * max_redun

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        if best_idx < 0:
            break

        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [payloads[i] for i in selected_indices]
