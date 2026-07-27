"""Targeted ingest: include all relevant docs from qrels + N distractors for LeCaRDv2 eval."""
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
    parser.add_argument("--chunk_size", type=int, default=1500)
    parser.add_argument("--chunk_overlap", type=int, default=150)
    parser.add_argument("--lance_dir", type=str, required=True,
                        help="LanceDB directory (must contain 'experiment')")
    parser.add_argument("--n_distractors", type=int, default=500,
                        help="Number of random distractors (non-relevant docs)")
    args = parser.parse_args()

    assert "experiment" in args.lance_dir, \
        f"SAFETY: lance_dir must contain 'experiment', got '{args.lance_dir}'"

    # Load qrels to find all relevant doc IDs
    with open(os.path.join(DATA_DIR, "qrels.json"), encoding="utf-8") as f:
        qrels = json.load(f)
    needed_docs = set()
    for qid, docs in qrels.items():
        needed_docs.update(docs.keys())
    print(f"Relevant doc IDs from qrels: {len(needed_docs)}")

    # Load ALL corpus and separate relevant vs distractor
    corpus_path = os.path.join(DATA_DIR, "corpus.jsonl")
    relevant = []
    distractors = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            doc_id = str(row.get("_id", row.get("id", "")))
            if doc_id in needed_docs:
                relevant.append(row)
            else:
                distractors.append(row)

    print(f"Relevant docs found: {len(relevant)}, Distractors available: {len(distractors)}")

    # Sample distractors
    random.seed(42)
    sample_dist = random.sample(distractors, min(args.n_distractors, len(distractors)))
    all_docs = relevant + sample_dist
    print(f"Total docs to ingest: {len(all_docs)} ({len(relevant)} relevant + {len(sample_dist)} distractors)")

    # Chunk
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", "。", "，", " ", ""],
    )

    langchain_docs = []
    for raw in all_docs:
        doc_id = str(raw.get("_id", raw.get("id", str(len(langchain_docs)))))
        text = raw.get("text", "")
        chunks = splitter.split_text(text)
        for ci, ct in enumerate(chunks):
            langchain_docs.append(Document(
                page_content=ct,
                metadata={
                    "title": f"source=lecardv2, doc_id={doc_id}, chunk={ci}",
                    "resource_id": doc_id,
                    "doc_id": doc_id,
                    "chunk_idx": ci,
                    "belongs_to": USER_EMAIL,
                    "user_id": str(USER_ID),
                    "source_type": "note",
                    "source": "lecardv2",
                }))

    print(f"Chunked into {len(langchain_docs)} chunks "
          f"(avg {len(langchain_docs)/max(len(all_docs),1):.1f}/doc)")

    # Monkeypatch + connect
    from backend.config import settings
    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = args.lance_dir
    import lancedb
    import backend.vector_store.lance_db as ldb
    ldb.db = lancedb.connect(args.lance_dir)
    if settings.VECTOR_STORE_COLLECTION_NAME not in ldb.db.table_names():
        ldb.initialize_collection()

    # Ingest
    from backend.vector_store.lance_db import add_documents
    BATCH = 100
    t0 = time.time()
    for i in range(0, len(langchain_docs), BATCH):
        add_documents(langchain_docs[i:i+BATCH])
        print(f"  Ingested {min(i+BATCH, len(langchain_docs))}/{len(langchain_docs)} "
              f"({time.time()-t0:.0f}s)")

    print(f"Done. {len(langchain_docs)} chunks in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
