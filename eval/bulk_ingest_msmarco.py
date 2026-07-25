"""Bulk ingest MS MARCO passages directly into LanceDB + FTS5.

In-process, no HTTP queue. Uses existing add_documents entry point.
Much faster than 3073 individual POST /file/note + queue + worker cycles.

Architecture: LangChain Document → embed_documents (batch) → LanceDB + FTS5.
"""
import os, sys, json, time, random

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from langchain.schema import Document

SAMPLE_FILE = "eval/sample_1000.json"
COLLECTION = "eval/msmarco_data/collection.tsv"
USER_ID = 1
USER_EMAIL = "10000@qq.com"


def main():
    # 1. Load sample
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)

    # 2. Collect relevant passages
    needed = set()
    passages = {}
    for s in samples:
        for pid, text in zip(s["relevant_pids"], s["relevant_passages"]):
            needed.add(pid)
            passages[pid] = text

    print(f"Relevant passages: {len(passages)}")

    # 3. Add distractors from collection first N lines
    random.seed(42)
    candidates = []
    with open(COLLECTION, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i > 500000:
                break
            parts = line.strip().split("\t", 1)
            if len(parts) >= 2 and parts[0] not in needed:
                candidates.append((parts[0], parts[1]))

    distractor_list = random.sample(candidates, min(2000, len(candidates)))
    for pid, text in distractor_list:
        passages[pid] = text

    print(f"Total passages: {len(passages)} ({len(needed)} relevant + {len(distractor_list)} distractors)")

    # 4. Build LangChain Documents
    t0 = time.time()
    docs = []
    for pid, text in passages.items():
        doc = Document(
            page_content=text,
            metadata={
                "title": f"source=msmarco, pid={pid}",
                "pid": pid,
                "belongs_to": USER_EMAIL,
                "user_id": str(USER_ID),
                "source_type": "note",
                "source": "msmarco",
            },
        )
        docs.append(doc)

    print(f"Built {len(docs)} LangChain Documents in {time.time()-t0:.1f}s")

    # 5. Ingest in batches using existing add_documents
    from backend.vector_store.lance_db import add_documents

    BATCH = 100
    n_done = 0
    for i in range(0, len(docs), BATCH):
        batch = docs[i : i + BATCH]
        t1 = time.time()
        try:
            add_documents(batch)
            n_done += len(batch)
            rate = len(batch) / (time.time() - t1 + 0.001)
            print(f"  [{n_done}/{len(docs)}] batch OK ({rate:.0f} docs/s)")
        except Exception as e:
            print(f"  [ERROR] batch {i}: {type(e).__name__}: {e}")

    elapsed = time.time() - t0
    print(f"\nBulk ingest complete: {len(docs)} passages in {elapsed:.1f}s ({len(docs)/elapsed:.1f} docs/s)")


if __name__ == "__main__":
    main()
