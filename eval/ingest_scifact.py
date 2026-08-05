"""
Ingest SciFact corpus into wenjv knowledge base as notes.

Usage:
  cd inquisitive-master
  python eval/ingest_scifact.py --count 100 --user-email your@email.com

What it does:
  1. Reads SciFact corpus documents
  2. Creates notes via POST /file/note (needs backend running + JWT token)
  3. Waits for ingestion jobs to complete
  4. Ready for eval/run_scifact.py

Requirements:
  - Backend running on localhost:8000
  - A registered user with valid JWT token
  - pip install httpx (already in your requirements)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import httpx

SCIFACT_BASE = "C:/Users/Lanzao/Downloads/scifact/scifact"
BACKEND_URL = "http://127.0.0.1:8000"

# Max concurrent note creations (backend worker handles embedding)
MAX_CONCURRENT = 5


def load_corpus(limit=0):
    """Load SciFact corpus, return list of {_id, title, text}."""
    corpus_file = os.path.join(SCIFACT_BASE, "corpus.jsonl")
    docs = []
    with open(corpus_file) as f:
        for line in f:
            doc = json.loads(line)
            docs.append(doc)
            if limit and len(docs) >= limit:
                break
    return docs


def get_token(email: str, password: str):
    """Login and get JWT token."""
    import httpx

    with httpx.Client() as client:
        # Login via fastapi-users
        resp = client.post(
            f"{BACKEND_URL}/auth/jwt/login",
            data={"username": email, "password": password},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Login failed ({resp.status_code}): {resp.text}\n"
                f"  Make sure backend is running and user '{email}' is registered."
            )
        return resp.json()["access_token"]


async def create_note(client: httpx.AsyncClient, token: str, title: str, content: str):
    """Create a note via the API."""
    resp = await client.post(
        f"{BACKEND_URL}/file/note",
        json={"title": title, "content": content},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    return resp


async def ingest_batch(docs, token: str, start_idx: int = 0, count: int = 0):
    """Create notes for a batch of SciFact docs."""
    if count:
        docs = docs[start_idx : start_idx + count]

    total = len(docs)
    print(f"Creating {total} notes (this triggers embedding jobs)...")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    created = 0
    failed = 0
    t0 = time.time()

    async def create_one(idx: int, doc: dict):
        nonlocal created, failed
        async with semaphore:
            try:
                async with httpx.AsyncClient() as client:
                    # Use title as note title, text as content
                    title = doc["title"][:200]  # truncate long titles
                    content = doc["text"]
                    resp = await create_note(client, token, title, content)
                    if resp.status_code in (200, 201, 202):
                        created += 1
                    else:
                        failed += 1
                        if failed <= 3:  # only print first few errors
                            print(f"  FAIL [{idx}]: {resp.status_code} {resp.text[:100]}")
                    return resp.status_code
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"  ERROR [{idx}]: {e}")
                return None

    tasks = [create_one(i, doc) for i, doc in enumerate(docs, start=start_idx)]
    await asyncio.gather(*tasks)

    elapsed = time.time() - t0
    print(f"Done: {created} created, {failed} failed ({elapsed:.1f}s)")
    print(f"Notes are now queued for embedding. Check /jobs for status.")
    print(f"Run `python eval/run_scifact.py` after jobs complete.")


def main():
    parser = argparse.ArgumentParser(description="Ingest SciFact corpus into wenjv")
    parser.add_argument("--count", type=int, default=50,
                        help="How many docs to ingest (default: 50, 0=all)")
    parser.add_argument("--start", type=int, default=0,
                        help="Start index (for resuming)")
    parser.add_argument("--email", type=str, required=True,
                        help="Your wenjv user email")
    parser.add_argument("--password", type=str, default="password",
                        help="Your wenjv user password")
    parser.add_argument("--list", action="store_true",
                        help="Just list what would be ingested")
    parser.add_argument("--token", type=str, default="",
                        help="Skip login, use this JWT token directly")
    args = parser.parse_args()

    docs = load_corpus()
    print(f"SciFact corpus: {len(docs)} total documents")

    if args.count:
        docs = docs[args.start : args.start + args.count]
    elif args.start:
        docs = docs[args.start:]

    if args.list:
        print(f"\nWould ingest {len(docs)} notes:")
        for i, doc in enumerate(docs[:10]):
            print(f"  [{i+1}] {doc['title'][:80]}")
        if len(docs) > 10:
            print(f"  ... and {len(docs) - 10} more")
        return

    if not args.token:
        print(f"\nLogging in as {args.email}...")
        token = get_token(args.email, args.password)
        print("Login OK")
    else:
        token = args.token

    print(f"\nWill create {len(docs)} notes. Proceed? [y/N] ", end="", flush=True)
    answer = sys.stdin.readline().strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    asyncio.run(ingest_batch(docs, token, args.start))


if __name__ == "__main__":
    main()
