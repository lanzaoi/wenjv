"""SciFact A/B eval: hybrid ON vs OFF, direct call (no API restart needed).

Runs search_documents() directly, monkeypatching settings between runs.
"""
import json, os, sys, time

# Ensure project root on path
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

BASE = "C:/Users/Lanzao/Downloads/scifact/scifact"
MAX_QUERIES = 20
WINDOW = 10

def load_data():
    qrels, queries, corpus = {}, {}, {}
    with open(f"{BASE}/qrels/test.tsv") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("query-id"): continue
            qid, cid = line.split("\t")[:2]
            qrels.setdefault(qid, set()).add(cid)
    with open(f"{BASE}/queries.jsonl") as f:
        for line in f:
            q = json.loads(line)
            queries[q["_id"]] = q["text"]
    with open(f"{BASE}/corpus.jsonl") as f:
        for line in f:
            doc = json.loads(line)
            corpus[doc["_id"]] = {"title": doc["title"], "text": doc["text"]}
    test_qids = sorted([q for q in qrels if q in queries and qrels[q]], key=lambda x: int(x))[:MAX_QUERIES]
    return corpus, queries, qrels, test_qids

def run_queries(hybrid_enabled):
    from backend.api.services.search import search_documents
    from backend.config import settings
    
    settings.HYBRID_SEARCH_ENABLED = hybrid_enabled
    mode = "HYBRID ON" if hybrid_enabled else "VECTOR ONLY"
    
    corpus, queries, qrels, test_qids = load_data()
    results = {}
    r5_total = r10_total = 0.0
    
    for qid in test_qids:
        question = queries[qid]
        relevant = qrels.get(qid, set())
        
        t0 = time.time()
        docs = search_documents(
            prompt=question,
            user_email="10000@qq.com",
            window_size=WINDOW,
            user_id=1,
        )
        elapsed = time.time() - t0
        
        # Match retrieved docs back to SciFact IDs
        from backend.api.services.search import format_search_hits
        hits, _ = format_search_hits(docs, source_type=None, window_size=WINDOW)
        retrieved_ids = []
        for doc, score, source in hits:
            meta = doc.metadata
            title = (meta.get("title") or "").strip()
            filename = (meta.get("filename") or "")
            # Match title to corpus
            if title:
                for cid, item in corpus.items():
                    if item["title"] == title:
                        retrieved_ids.append(cid)
                        break
            elif filename:
                name = filename.replace(".md", "")
                for cid, item in corpus.items():
                    slug = item["title"].lower().replace(" ", "-").replace(":", "").replace("'", "")[:60]
                    if slug and slug in name.lower():
                        retrieved_ids.append(cid)
                        break
        
        r5 = len(set(retrieved_ids[:5]) & relevant) / len(relevant) if relevant else 0
        r10 = len(set(retrieved_ids[:10]) & relevant) / len(relevant) if relevant else 0
        r5_total += r5; r10_total += r10
        results[qid] = (r5, r10, len(retrieved_ids), elapsed)
    
    n = len(test_qids)
    print(f"\n  Recall@5:  {r5_total/n:.3f}   Recall@10: {r10_total/n:.3f}")
    print(f"  ({sum(1 for v in results.values() if v[0] > 0)}/{n} queries hit @5)")
    return results, r5_total/n, r10_total/n

def main():
    print("="*60)
    print("SciFact A/B: Hybrid ON vs OFF (20 queries, kernel=10)")
    print("="*60)
    
    print("\n--- HYBRID ON (Vector + FTS5 BM25 → RRF) ---")
    res_on, r5_on, r10_on = run_queries(True)
    
    print("\n--- VECTOR ONLY (hybrid OFF) ---")
    res_off, r5_off, r10_off = run_queries(False)
    
    print(f"\n{'='*60}")
    print(f"COMPARISON:")
    print(f"  Hybrid ON:  R@5={r5_on:.3f}  R@10={r10_on:.3f}")
    print(f"  Hybrid OFF: R@5={r5_off:.3f}  R@10={r10_off:.3f}")
    delta5 = r5_on - r5_off
    delta10 = r10_on - r10_off
    print(f"  Δ:          R@5={'+' if delta5>=0 else ''}{delta5:.3f}  R@10={'+' if delta10>=0 else ''}{delta10:.3f}")
    
    if delta5 > 0:
        print(f"\n  ✓ Hybrid improves Recall@5 by {delta5:.1%}")
    elif delta5 < 0:
        print(f"\n  ✗ Hybrid HURTS Recall@5 by {abs(delta5):.1%}")
    else:
        print(f"\n  = Hybrid has no effect on Recall@5")

if __name__ == "__main__":
    main()
