"""Fast targeted ingest for LeCaRDv2: only include docs relevant to first N queries + few distractors."""
import os, sys, json, time, argparse, random

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

DATA_DIR = "eval/lecardv2_data"
USER_ID = 1
USER_EMAIL = "10000@qq.com"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lance_dir", type=str, required=True)
    parser.add_argument("--max_queries", type=int, default=20, help="Only include docs relevant to first N queries")
    parser.add_argument("--n_distractors", type=int, default=50)
    parser.add_argument("--chunk_size", type=int, default=1500)
    parser.add_argument("--chunk_overlap", type=int, default=150)
    args = parser.parse_args()

    assert "experiment" in args.lance_dir

    # Load qrels, take first N queries
    with open(os.path.join(DATA_DIR, "qrels.json"), encoding="utf-8") as f:
        all_qrels = json.load(f)
    query_ids = list(all_qrels.keys())[:args.max_queries]
    qrels = {qid: all_qrels[qid] for qid in query_ids}
    needed_docs = set()
    for qid, docs in qrels.items():
        needed_docs.update(docs.keys())
    print(f"Queries: {len(qrels)}, Relevant docs: {len(needed_docs)}")

    # Save subset queries (for eval to use same subset)
    with open(os.path.join(DATA_DIR, "queries.json"), encoding="utf-8") as f:
        all_queries = json.load(f)
    queries_subset = {qid: all_queries[str(qid)] for qid in query_ids if str(qid) in all_queries}
    with open("eval/lecardv2_data/queries_subset.json", "w", encoding="utf-8") as f:
        json.dump(queries_subset, f, ensure_ascii=False, indent=2)
    with open("eval/lecardv2_data/qrels_subset.json", "w", encoding="utf-8") as f:
        json.dump(qrels, f, ensure_ascii=False, indent=2)
    print(f"Saved subset: {len(queries_subset)} queries, {sum(len(v) for v in qrels.values())} qrel pairs")

    # Load corpus, separate relevant vs distractor
    corpus_path = os.path.join(DATA_DIR, "corpus.jsonl")
    relevant = []
    distractors = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            doc_id = str(row.get("_id", ""))
            if doc_id in needed_docs:
                relevant.append(row)
            else:
                distractors.append(row)

    print(f"Relevant: {len(relevant)}, Distractors pool: {len(distractors)}")

    random.seed(42)
    sample_dist = random.sample(distractors, min(args.n_distractors, len(distractors)))
    all_docs = relevant + sample_dist
    print(f"Ingesting: {len(all_docs)} docs")

    # Chunk
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap,
        length_function=len, separators=["\n\n", "\n", "。", "，", " ", ""],
    )

    langchain_docs = []
    for raw in all_docs:
        doc_id = str(raw.get("_id", ""))
        text = raw.get("text", "")
        chunks = splitter.split_text(text)
        for ci, ct in enumerate(chunks):
            langchain_docs.append(Document(
                page_content=ct,
                metadata={
                    "title": f"source=lecardv2, doc_id={doc_id}, chunk={ci}",
                    "resource_id": doc_id, "doc_id": doc_id, "chunk_idx": ci,
                    "belongs_to": USER_EMAIL, "user_id": str(USER_ID),
                    "source_type": "note", "source": "lecardv2",
                }))
    print(f"Chunked: {len(langchain_docs)} chunks (avg {len(langchain_docs)/max(len(all_docs),1):.1f}/doc)")

    # Connect
    from backend.config import settings
    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = args.lance_dir
    import lancedb, backend.vector_store.lance_db as ldb
    ldb.db = lancedb.connect(args.lance_dir)
    if settings.VECTOR_STORE_COLLECTION_NAME not in ldb.db.table_names():
        ldb.initialize_collection()

    # Ingest
    from backend.vector_store.lance_db import add_documents
    BATCH = 100
    t0 = time.time()
    for i in range(0, len(langchain_docs), BATCH):
        add_documents(langchain_docs[i:i+BATCH])
        elapsed = time.time() - t0
        pct = min(i+BATCH, len(langchain_docs)) / len(langchain_docs) * 100
        eta = elapsed / (pct/100) - elapsed if pct > 0 else 0
        print(f"  {min(i+BATCH, len(langchain_docs))}/{len(langchain_docs)} ({elapsed:.0f}s, ETA {eta:.0f}s)")

    print(f"Done: {len(langchain_docs)} chunks in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
