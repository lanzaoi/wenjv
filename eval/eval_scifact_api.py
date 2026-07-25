"""Quick SciFact eval: search API → compare qrels → print Recall@K.

Usage:
  cd inquisitive-master
  venv/Scripts/python eval/eval_scifact_api.py
"""
import json, os, sys, time, httpx

BASE = "C:/Users/Lanzao/Downloads/scifact/scifact"
API = "http://127.0.0.1:8000"
EMAIL = "10000@qq.com"
PASSWORD = "10000"
MAX_QUERIES = 15   # how many test queries to run
WINDOW_SIZE = 10   # top-K for recall calculation

# ---- load data ----
def load_sci():
    qrels = {}
    with open(f"{BASE}/qrels/test.tsv") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("query-id"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                qrels.setdefault(parts[0], set()).add(parts[1])

    queries = {}
    with open(f"{BASE}/queries.jsonl") as f:
        for line in f:
            q = json.loads(line)
            queries[q["_id"]] = q["text"]

    corpus = {}
    with open(f"{BASE}/corpus.jsonl") as f:
        for line in f:
            doc = json.loads(line)
            corpus[doc["_id"]] = {"title": doc["title"], "text": doc["text"]}

    # pick queries that have qrels + text
    test_qids = sorted(
        [qid for qid in qrels if qid in queries and qrels[qid]],
        key=lambda x: int(x),
    )[:MAX_QUERIES]

    return corpus, queries, qrels, test_qids


def login():
    r = httpx.post(f"{API}/auth/jwt/login",
                   data={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


def search(token, question):
    r = httpx.post(f"{API}/documents/search",
                   json={"prompt": question, "window_size": WINDOW_SIZE},
                   headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


def match_scifact_id(doc_meta, corpus, content=""):
    """Match retrieved note back to SciFact corpus ID.
    Uses title from metadata, falls back to content prefix matching.
    """
    title = (doc_meta.get("title") or "").strip()
    filename = (doc_meta.get("filename") or "")
    
    # Direct title match (fast path)
    if title:
        for cid, item in corpus.items():
            if item["title"] == title:
                return cid
    
    # Extract title from filename (format: Title-here-uuid.md)
    if filename:
        # Remove .md and UUID suffix, reconstruct title
        name = filename.replace(".md", "")
        # Try matching by slug-like comparison
        for cid, item in corpus.items():
            corpus_title = item["title"]
            # Check if corpus title is contained in filename slug
            title_slug = corpus_title.lower().replace(" ", "-").replace(":", "").replace("'", "")[:60]
            if title_slug and title_slug in name.lower():
                return cid
            # Also check if the filename starts with the corpus title prefix
            if name.lower().startswith(title_slug[:30]):
                return cid
    
    # Content prefix matching (slow, last resort)
    if content:
        prefix = content.strip()[:80]
        for cid, item in corpus.items():
            if item["text"].strip()[:80] == prefix:
                return cid
    
    return None


def main():
    corpus, queries, qrels, test_qids = load_sci()
    print(f"SciFact: {len(test_qids)} queries, corpus has {len(corpus)} docs")

    token = login()
    print("Logged in")

    results = []
    recall_at_5 = 0.0
    recall_at_10 = 0.0
    total = 0

    for qid in test_qids:
        question = queries[qid]
        relevant = qrels.get(qid, set())

        t0 = time.time()
        try:
            resp = search(token, question)
        except Exception as e:
            print(f"  Q{qid}: API ERROR {e}")
            continue

        docs = resp.get("documents", [])
        retrieved_ids = []
        for doc in docs:
            cid = match_scifact_id(
                doc.get("metadata", {}), corpus,
                content=doc.get("page_content", "")
            )
            if cid:
                retrieved_ids.append(cid)

        elapsed = time.time() - t0

        rel5 = set(retrieved_ids[:5]) & relevant
        rel10 = set(retrieved_ids[:10]) & relevant
        r5 = len(rel5) / len(relevant) if relevant else 0
        r10 = len(rel10) / len(relevant) if relevant else 0

        recall_at_5 += r5
        recall_at_10 += r10
        total += 1

        status = "✓" if r5 > 0 else "✗"
        results.append((qid, question[:80], r5, r10, elapsed, len(retrieved_ids)))

        if total <= 10 or total % 5 == 0:
            print(
                f"  [{total:2d}] Q{qid} {status} "
                f"R@5={r5:.2f} R@10={r10:.2f} "
                f"({len(retrieved_ids)} matched docs, {elapsed:.1f}s)"
            )

    print(f"\n{'='*50}")
    if total:
        print(f"Recall@5:  {recall_at_5/total:.3f}")
        print(f"Recall@10: {recall_at_10/total:.3f}")
    print(f"Queries: {total}, Avg matched: {sum(r[5] for r in results)/max(total,1):.1f}")

    # Show per-query detail
    print(f"\n{'='*50}")
    print("Per-query detail:")
    for qid, qtext, r5, r10, elapsed, nmatched in results:
        print(f"  Q{qid:>3s} R@5={r5:.2f} R@10={r10:.2f} matched={nmatched}  {qtext[:60]}")


if __name__ == "__main__":
    main()
