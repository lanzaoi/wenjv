"""Bulk ingest LeCaRDv2 documents into isolated LanceDB for document-level eval."""
import os, sys, json, time, argparse

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
    parser.add_argument("--max_docs", type=int, default=3795)
    parser.add_argument("--chunk_size", type=int, default=1500)
    parser.add_argument("--chunk_overlap", type=int, default=150)
    parser.add_argument("--lance_dir", type=str, required=True,
                        help="LanceDB directory (must contain 'experiment')")
    args = parser.parse_args()

    assert "experiment" in args.lance_dir, \
        f"SAFETY: lance_dir must contain 'experiment', got '{args.lance_dir}'"

    # Load corpus
    corpus_path = os.path.join(DATA_DIR, "corpus.jsonl")
    docs_raw = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= args.max_docs:
                break
            docs_raw.append(json.loads(line))
    print(f"Loaded {len(docs_raw)} raw documents")

    # Chunk each document with Chinese-aware separators
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", "。", "，", " ", ""],
    )

    langchain_docs = []
    for raw in docs_raw:
        doc_id = str(raw.get("_id", raw.get("id", str(len(langchain_docs)))))
        title = raw.get("title", "")
        text = raw.get("text", "")

        chunks = splitter.split_text(text)
        for ci, chunk_text in enumerate(chunks):
            doc = Document(
                page_content=chunk_text,
                metadata={
                    "title": f"source=lecardv2, doc_id={doc_id}, chunk={ci}",
                    "resource_id": doc_id,
                    "doc_id": doc_id,
                    "chunk_idx": ci,
                    "belongs_to": USER_EMAIL,
                    "user_id": str(USER_ID),
                    "source_type": "note",
                    "source": "lecardv2",
                },
            )
            langchain_docs.append(doc)

    print(
        f"Chunked into {len(langchain_docs)} chunks "
        f"({len(docs_raw)} docs, "
        f"avg {len(langchain_docs) / max(len(docs_raw), 1):.1f} chunks/doc)"
    )

    # Monkeypatch LanceDB path
    from backend.config import settings

    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = args.lance_dir

    # Batch ingest
    from backend.vector_store.lance_db import add_documents

    BATCH = 100
    t0 = time.time()
    for i in range(0, len(langchain_docs), BATCH):
        batch = langchain_docs[i : i + BATCH]
        add_documents(batch)
        print(
            f"  Ingested {min(i + BATCH, len(langchain_docs))}/{len(langchain_docs)} "
            f"({time.time() - t0:.1f}s)"
        )

    print(f"Done. {len(langchain_docs)} chunks in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
