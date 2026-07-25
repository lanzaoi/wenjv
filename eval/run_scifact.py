"""
SciFact eval runner — offline, calls search_documents directly (no HTTP server needed).

Usage:
  cd inquisitive-master
  . venv/Scripts/activate
  python eval/run_scifact.py          # default: hybrid OFF
  python eval/run_scifact.py --hybrid # hybrid ON

What it does:
  1. Picks a subset of SciFact corpus + queries
  2. Creates a minimal note for each doc (no embedding needed for keyword side)
  3. Calls search_documents() for each query
  4. Computes Recall@5, Recall@10, and prints per-query results
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict

# Ensure project root on path so `from backend...` works
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCIFACT_BASE = "C:/Users/Lanzao/Downloads/scifact/scifact"
MAX_DOCS = 300          # how many corpus docs to load (0 = all 5183)
MAX_QUERIES = 30        # how many test queries to run (0 = all 300)

HYBRID_ENABLED = False
FTS5_ENABLED = False    # set True if chunks_fts table is populated


def load_scifact(limit_docs=300, limit_queries=30):
    """Return corpus, queries, qrels as Python dicts."""
    corpus_file = os.path.join(SCIFACT_BASE, "corpus.jsonl")
    queries_file = os.path.join(SCIFACT_BASE, "queries.jsonl")
    qrels_file = os.path.join(SCIFACT_BASE, "qrels", "test.tsv")

    # --- qrels (ground truth) ---
    qrels = defaultdict(set)       # query_id -> set of corpus_ids
    with open(qrels_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("query-id"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                qrels[parts[0]].add(parts[1])

    # --- queries ---
    queries = {}
    with open(queries_file) as f:
        for line in f:
            q = json.loads(line)
            queries[q["_id"]] = q["text"]

    # --- corpus ---
    corpus = {}
    with open(corpus_file) as f:
        for line in f:
            doc = json.loads(line)
            corpus[doc["_id"]] = {"title": doc["title"], "text": doc["text"]}

    # --- pick test queries ---
    test_qids = sorted(
        [qid for qid in qrels if qid in queries],
        key=lambda x: int(x),
    )
    if limit_queries:
        test_qids = test_qids[:limit_queries]

    # --- pick corpus docs that are relevant to our test queries ---
    needed_ids = set()
    for qid in test_qids:
        needed_ids |= qrels[qid]

    # also add random docs as distractors
    import random
    random.seed(42)
    all_ids = list(corpus.keys())
    other_ids = [cid for cid in all_ids if cid not in needed_ids]
    random.shuffle(other_ids)

    selected = list(needed_ids) + other_ids
    if limit_docs and len(selected) > limit_docs:
        # keep all needed + fill with random
        selected = list(needed_ids) + other_ids[: max(0, limit_docs - len(needed_ids))]

    corpus = {cid: corpus[cid] for cid in selected if cid in corpus}

    return corpus, queries, qrels, test_qids


def make_lance_docs(corpus):
    """Convert scifact corpus -> list of (doc_id, page_content, metadata_dict)."""
    from langchain.schema import Document

    docs = []
    for cid, item in corpus.items():
        text = f"{item['title']}\n\n{item['text']}"
        metadata = {
            "id": cid,
            "title": item["title"],
            "source_type": "note",
        }
        docs.append((Document(page_content=text, metadata=metadata), 0.0))
    return docs


def run_eval(corpus, queries, qrels, test_qids, hybrid=False, fts5=False):
    """Run retrieval for each query, compute recall metrics."""
    # Try real search pipeline first; fall back to text matching
    try:
        from backend.api.services import search as search_service
        from backend.config import settings
        _HAS_BACKEND = True
    except ImportError:
        _HAS_BACKEND = False
        print("(backend module not available — using text-match fallback)")

    print(f"Corpus: {len(corpus)} docs | Queries: {len(test_qids)}")
    print(f"Hybrid: {hybrid} | FTS5: {fts5} | Real backend: {_HAS_BACKEND}")
    print(f"{'='*60}")

    if _HAS_BACKEND:
        old_hybrid = getattr(settings, "HYBRID_SEARCH_ENABLED", False)
        old_backend = getattr(settings, "HYBRID_KEYWORD_BACKEND", "fts5")
        settings.HYBRID_SEARCH_ENABLED = hybrid
        settings.HYBRID_KEYWORD_BACKEND = "fts5" if fts5 else "like"

    recall_at_5 = 0
    recall_at_10 = 0
    total = 0
    results = []

    try:
        for qid in test_qids:
            question = queries[qid]
            relevant = qrels.get(qid, set())

            t0 = time.time()
            try:
                if _HAS_BACKEND:
                    # --- Real pipeline ---
                    docs = search_service.search_documents(
                        prompt=question,
                        user_email="eval@scifact",
                        window_size=10,
                        user_id=1,
                    )
                    hits, _ = search_service.format_search_hits(docs, source_type=None, window_size=10)
                    retrieved_ids = [doc.metadata.get("id") for doc, _, _ in hits[:10]]
                else:
                    # --- Text-match fallback ---
                    hits = []
                    for cid, item in corpus.items():
                        text = f"{item['title']}\n\n{item['text']}"
                        metadata = {"id": cid, "title": item["title"]}
                        # Minimal Document-like (avoid langchain import in fallback mode)
                        class _Doc:
                            def __init__(self, page_content, metadata):
                                self.page_content = page_content
                                self.metadata = metadata
                        doc = _Doc(text, metadata)
                        # Very rough: score by case-insensitive word overlap
                        q_words = set(question.lower().split())
                        t_words = set(text.lower().split())
                        overlap = len(q_words & t_words)
                        score = -overlap  # negative so fewer words → larger distance
                        hits.append((doc, score))
                    hits.sort(key=lambda x: x[1])
                    retrieved_ids = [doc.metadata.get("id") for doc, _ in hits[:10]]
            except Exception as e:
                print(f"  Q{qid}: ERROR {e}")
                retrieved_ids = []

            elapsed = time.time() - t0

            # Compute recall
            rel_retrieved = set(retrieved_ids[:5]) & relevant
            rel_retrieved_10 = set(retrieved_ids[:10]) & relevant
            r5 = len(rel_retrieved) / len(relevant) if relevant else 0
            r10 = len(rel_retrieved_10) / len(relevant) if relevant else 0

            recall_at_5 += r5
            recall_at_10 += r10
            total += 1

            status = "✓" if r5 > 0 else "✗"
            results.append((qid, question[:80], r5, r10, elapsed))

            if total <= 10 or total % 10 == 0:
                print(
                    f"  [{total:3d}/{len(test_qids)}] Q{qid} {status} "
                    f"R@5={r5:.2f} R@10={r10:.2f} ({elapsed:.2f}s)"
                )

    finally:
        if _HAS_BACKEND:
            settings.HYBRID_SEARCH_ENABLED = old_hybrid
            settings.HYBRID_KEYWORD_BACKEND = old_backend

    print(f"{'='*60}")
    if total:
        print(f"Recall@5:  {recall_at_5/total:.3f}  ({recall_at_5:.0f}/{total})")
        print(f"Recall@10: {recall_at_10/total:.3f}  ({recall_at_10:.0f}/{total})")
    print(f"Avg time: {sum(r[4] for r in results)/len(results):.3f}s" if results else "")

    return results


# ---------------------------------------------------------------------------
# Placeholder — real eval needs actual vector store
# This script is a template; the real search runs through your Lance/Chroma
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid", action="store_true")
    parser.add_argument("--fts5", action="store_true")
    parser.add_argument("--max-docs", type=int, default=MAX_DOCS)
    parser.add_argument("--max-queries", type=int, default=MAX_QUERIES)
    parser.add_argument("--list", action="store_true",
                        help="Just show dataset stats, don't run eval")
    args = parser.parse_args()

    corpus, queries, qrels, test_qids = load_scifact(args.max_docs, args.max_queries)

    if args.list:
        print(f"=== SciFact Stats ===")
        print(f"Selected corpus:  {len(corpus)} docs")
        print(f"Test queries:     {len(test_qids)}")
        relevant = set()
        for qid in test_qids:
            relevant |= qrels[qid]
        print(f"Relevant in set:  {len(relevant)} docs")
        print(f"\n=== First 5 queries ===")
        for qid in test_qids[:5]:
            print(f"  Q{qid}: {queries[qid][:100]}")
            for cid in list(qrels[qid])[:2]:
                if cid in corpus:
                    print(f"       → [{corpus[cid]['title'][:80]}]")
        return

    print("=" * 60)
    print("NOTE: This template script needs integration with your actual")
    print("search_documents() pipeline. The placeholder just does text matching.")
    print("To run real eval:")
    print("  1. Start backend + ingest corpus docs as notes")
    print("  2. Run queries against POST /documents/search or /chat")
    print("  3. Compare results to qrels")
    print("=" * 60)
    print()

    run_eval(corpus, queries, qrels, test_qids, args.hybrid, args.fts5)


if __name__ == "__main__":
    main()
