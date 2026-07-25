"""Ingest SPECIFIC SciFact docs by their corpus IDs (from qrels), plus distractors."""
import json, os, sys, httpx, asyncio, time

BASE = "C:/Users/Lanzao/Downloads/scifact/scifact"
API = "http://127.0.0.1:8000"
EMAIL = "10000@qq.com"
PASSWORD = "10000"
DISTRACTORS = 50  # extra random docs as noise

def load_corpus():
    corpus = {}
    with open(f"{BASE}/corpus.jsonl") as f:
        for line in f:
            doc = json.loads(line)
            corpus[doc["_id"]] = doc
    return corpus

def get_needed_ids(n_queries=30):
    qrels = {}
    with open(f"{BASE}/qrels/test.tsv") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("query-id"): continue
            qid, cid = line.split("\t")[:2]
            qrels.setdefault(qid, set()).add(cid)
    queries = {}
    with open(f"{BASE}/queries.jsonl") as f:
        for line in f:
            q = json.loads(line)
            queries[q["_id"]] = q["text"]
    test_qids = sorted([q for q in qrels if q in queries], key=lambda x: int(x))[:n_queries]
    needed = set()
    for qid in test_qids:
        needed |= qrels[qid]
    return needed, test_qids

def login():
    r = httpx.post(f"{API}/auth/jwt/login",
                   data={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]

async def ingest_ids(ids, token):
    corpus = load_corpus()
    missing = [cid for cid in ids if cid not in corpus]
    if missing:
        print(f"WARNING: {len(missing)} IDs not in corpus: {missing[:5]}...")
    docs = [(cid, corpus[cid]) for cid in ids if cid in corpus]
    
    sem = asyncio.Semaphore(5)
    ok = 0
    fail = 0
    
    async def create_one(cid, doc):
        nonlocal ok, fail
        async with sem:
            try:
                async with httpx.AsyncClient() as c:
                    content = doc["text"]
                    title = doc["title"][:200]
                    r = await c.post(f"{API}/file/note",
                        json={"title": title, "content": content},
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=30)
                    if r.status_code in (200, 201, 202):
                        ok += 1
                    else:
                        fail += 1
                        if fail <= 3:
                            print(f"  FAIL {cid}: {r.status_code}")
            except Exception as e:
                fail += 1
                if fail <= 3:
                    print(f"  ERR {cid}: {e}")

    tasks = [create_one(cid, doc) for cid, doc in docs]
    await asyncio.gather(*tasks)
    print(f"Relevant docs: {ok} created, {fail} failed")

async def main():
    needed_ids, test_qids = get_needed_ids(30)
    print(f"First {len(test_qids)} test queries need {len(needed_ids)} specific docs")
    
    # Also add random distractors
    corpus = load_corpus()
    import random; random.seed(123)
    all_ids = list(corpus.keys())
    other_ids = [cid for cid in all_ids if cid not in needed_ids]
    random.shuffle(other_ids)
    distractors = other_ids[:DISTRACTORS]
    
    all_to_ingest = list(needed_ids) + distractors
    print(f"Total to ingest: {len(all_to_ingest)} ({len(needed_ids)} relevant + {len(distractors)} distractors)")
    
    token = login()
    print("Logged in")
    
    await ingest_ids(all_to_ingest, token)
    print("Done. Wait for embedding, then run eval_scifact_api.py")

if __name__ == "__main__":
    asyncio.run(main())
