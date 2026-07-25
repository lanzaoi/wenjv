import os
import json
import random
import httpx
import asyncio
import time

DATA_DIR = "eval/msmarco_data"
COLLECTION_FILE = os.path.join(DATA_DIR, "collection.tsv")
SAMPLE_FILE = "eval/sample_1000.json"
API = "http://127.0.0.1:8000"
EMAIL = "10000@qq.com"
PASSWORD = "10000"

async def login():
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(f"{API}/auth/jwt/login", data={"username": EMAIL, "password": PASSWORD})
            r.raise_for_status()
            return r.json()["access_token"]
        except Exception as e:
            print(f"Failed to login. Please ensure the backend server is running at {API}.")
            print(e)
            return None

async def ingest_docs(docs, token):
    sem = asyncio.Semaphore(10)
    ok = 0
    fail = 0
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        async def create_one(pid, text):
            nonlocal ok, fail
            async with sem:
                try:
                    title = f"source=msmarco, pid={pid}"
                    r = await client.post(f"{API}/file/note",
                        json={"title": title, "content": text},
                        headers={"Authorization": f"Bearer {token}"})
                    if r.status_code in (200, 201, 202):
                        ok += 1
                    else:
                        fail += 1
                        if fail <= 5 or r.status_code == 401:
                            print(f"  [WARN] Ingest failed for {pid}: HTTP {r.status_code} - {r.text[:100]}")
                        if r.status_code == 401:
                            print("  [CRITICAL] 401 Unauthorized encountered. Halting further ingestion.")
                            raise httpx.HTTPStatusError("401 Unauthorized", request=r.request, response=r)
                except Exception as e:
                    fail += 1
                    if fail <= 5:
                        print(f"  [WARN] Exception for {pid}: {type(e).__name__}: {e}")

        tasks = [create_one(pid, text) for pid, text in docs]
        await asyncio.gather(*tasks, return_exceptions=True)
    return ok, fail

async def main():
    if not os.path.exists(SAMPLE_FILE):
        print(f"Error: {SAMPLE_FILE} not found. Run sample_msmarco.py first.")
        return
        
    token = await login()
    if not token:
        return
        
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)
        
    needed_pids = set()
    relevant_docs = {}
    
    for s in samples:
        for pid, text in zip(s["relevant_pids"], s["relevant_passages"]):
            needed_pids.add(pid)
            relevant_docs[pid] = text
            
    print(f"Loaded {len(relevant_docs)} relevant passages.")
    
    distractors = {}
    # Get 2000 distractors
    print("Sampling 2000 random distractors from collection.tsv...")
    with open(COLLECTION_FILE, "r", encoding="utf-8") as f:
        # Reservoir sampling or just read a chunk
        # To avoid reading the whole file, we can just read first 100k lines and sample
        candidates = []
        for i, line in enumerate(f):
            if i > 100000:
                break
            parts = line.strip().split("\t", 1)
            if len(parts) >= 2:
                pid, text = parts[0], parts[1]
                if pid not in needed_pids:
                    candidates.append((pid, text))
                    
        random.seed(42)
        distractor_list = random.sample(candidates, min(2000, len(candidates)))
        for pid, text in distractor_list:
            distractors[pid] = text

    all_docs = list(relevant_docs.items()) + list(distractors.items())
    print(f"Total to ingest: {len(all_docs)} ({len(relevant_docs)} relevant + {len(distractors)} distractors)")
    
    print("Starting ingestion...")
    ok, fail = await ingest_docs(all_docs, token)
    print(f"Ingestion API calls finished: {ok} succeeded, {fail} failed.")
    print("Note: The documents are now in the ingestion queue. You can check the worker logs to verify they succeeded.")

if __name__ == "__main__":
    asyncio.run(main())
