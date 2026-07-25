"""SciFact A/B eval: hybrid ON vs OFF, same queries, side-by-side comparison.

Usage:
  cd inquisitive-master
  venv/Scripts/python eval/eval_ab.py
"""
import json, os, sys, time, httpx

BASE = "C:/Users/Lanzao/Downloads/scifact/scifact"
API = "http://127.0.0.1:8000"
EMAIL = "10000@qq.com"
PASSWORD = "10000"
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

def login():
    r = httpx.post(f"{API}/auth/jwt/login", data={"username": EMAIL, "password": PASSWORD})
    return r.json()["access_token"]

def search_batch(token, queries, test_qids):
    results = {}
    for qid in test_qids:
        try:
            r = httpx.post(f"{API}/documents/search",
                json={"prompt": queries[qid], "window_size": WINDOW},
                headers={"Authorization": f"Bearer {token}"}, timeout=30)
            results[qid] = r.json().get("documents", [])
        except Exception as e:
            print(f"  Q{qid} ERROR: {e}")
            results[qid] = []
    return results

def match_id(meta, corpus, content=""):
    title = (meta.get("title") or "").strip()
    if title:
        for cid, item in corpus.items():
            if item["title"] == title:
                return cid
    filename = (meta.get("filename") or "")
    if filename:
        name = filename.replace(".md", "")
        for cid, item in corpus.items():
            slug = item["title"].lower().replace(" ", "-").replace(":", "").replace("'", "")[:60]
            if slug and slug in name.lower():
                return cid
    return None

def compute_recall(retrieved_docs, qrels, qid, corpus):
    relevant = qrels.get(qid, set())
    ids = []
    for doc in retrieved_docs:
        cid = match_id(doc.get("metadata", {}), corpus, doc.get("page_content", ""))
        if cid:
            ids.append(cid)
    r5 = len(set(ids[:5]) & relevant) / len(relevant) if relevant else 0
    r10 = len(set(ids[:10]) & relevant) / len(relevant) if relevant else 0
    return r5, r10, ids

def main():
    corpus, queries, qrels, test_qids = load_data()
    token = login()

    # --- Run HYBRID ON ---
    print("="*60)
    print("HYBRID ON (Vector + FTS5 BM25 → RRF)")
    print("="*60)
    results_on = search_batch(token, queries, test_qids)
    r5_on, r10_on = 0, 0
    for qid in test_qids:
        r5, r10, ids = compute_recall(results_on[qid], qrels, qid, corpus)
        r5_on += r5; r10_on += r10
    n = len(test_qids)
    print(f"\nRecall@5:  {r5_on/n:.3f}   Recall@10: {r10_on/n:.3f}")

    # --- Turn hybrid OFF ---
    # We need to restart backend with HYBRID_SEARCH_ENABLED=false
    # For now, read current config
    env_path = os.path.expanduser("~/.config/inquisitive/backend.env")
    print(f"\n⚠️  To run hybrid OFF comparison, set HYBRID_SEARCH_ENABLED=false in")
    print(f"   {env_path}")
    print(f"   Then restart backend and re-run with --off flag\n")

    # Show per-query detail
    print("Per-query (hybrid ON):")
    print(f"{'QID':>5s} {'R@5':>5s} {'R@10':>5s} {'matched':>7s}  Question")
    for qid in test_qids:
        r5, r10, ids = compute_recall(results_on[qid], qrels, qid, corpus)
        flag = "✓" if r5 > 0 else "✗"
        print(f"  {flag} {qid:>3s} {r5:4.1f}  {r10:4.1f}  {len(ids):4d}     {queries[qid][:65]}")

    # Save results for later comparison
    out = {"hybrid_on": {}, "test_qids": test_qids}
    for qid in test_qids:
        r5, r10, ids = compute_recall(results_on[qid], qrels, qid, corpus)
        out["hybrid_on"][qid] = {"r5": r5, "r10": r10, "matched": len(ids)}
    with open("eval/ab_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved eval/ab_results.json — run again after switching hybrid OFF to complete A/B")

if __name__ == "__main__":
    main()
