"""T4 Chunking 2.0 — clean eval. Two separators, inline everything, no singleton traps."""
import os, sys, json, asyncio, time, shutil, argparse

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

import lancedb
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from backend.config import settings as s
from backend.vector_store.lance_db import add_documents
from backend.api.services.search import search_documents, format_search_hits
from eval.scoring import score_hits, summarize

USER_ID = 1
USER_EMAIL = "10000@qq.com"
WINDOW_SIZE = 10
MAX_DOCS = 1000
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150

SEPARATORS_CONFIGS = {
    "current":  ["\n\n", "\n", "。", "，", " ", ""],
    "semantic": ["\n\n", "。", "！", "？", "；"],
}


def load_lecardv2(max_docs=MAX_DOCS):
    with open("eval/lecardv2_data/corpus.jsonl", encoding="utf-8") as f:
        docs_raw = [json.loads(line) for i, line in enumerate(f) if i < max_docs]
    with open("eval/lecardv2_data/queries.json", encoding="utf-8") as f:
        queries = json.load(f)
    with open("eval/lecardv2_data/qrels.json", encoding="utf-8") as f:
        qrels = json.load(f)
    return docs_raw, queries, qrels


def ingest(name, seps, docs_raw, lance_dir):
    print(f"  [{name}] Chunking {len(docs_raw)} docs with separators={[x for x in seps if x.strip()]} ...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
        length_function=len, separators=seps,
    )
    langchain_docs = []
    for raw in docs_raw:
        doc_id = str(raw.get("_id", raw.get("id", str(len(langchain_docs)))))
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

    # Monkeypatch LanceDB path + re-init
    s.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir
    import backend.vector_store.lance_db as ldb
    ldb.db = lancedb.connect(lance_dir)
    if s.VECTOR_STORE_COLLECTION_NAME not in ldb.db.table_names():
        ldb.initialize_collection()

    t0 = time.time()
    BATCH = 100
    for i in range(0, len(langchain_docs), BATCH):
        add_documents(langchain_docs[i:i+BATCH])
    elapsed = time.time() - t0
    print(f"  [{name}] Ingested {len(langchain_docs)} chunks in {elapsed:.0f}s")
    return langchain_docs


async def evaluate(name, lance_dir, queries, qrels):
    s.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir
    import backend.vector_store.lance_db as ldb
    ldb.db = lancedb.connect(lance_dir)

    s.HYBRID_SEARCH_ENABLED = True
    s.STRUCTURED_RECALL_ENABLED = True
    s.MMR_ENABLED = False
    s.RERANK_ENABLED = False
    s.QUERY_CLASSIFIER_ENABLED = False

    t0 = time.time()
    scores = []
    n_errors = 0
    n_done = 0
    for qid, query_text in queries.items():
        try:
            docs = await search_documents(
                prompt=query_text, user_email=USER_EMAIL,
                window_size=WINDOW_SIZE, user_id=USER_ID,
            )
            hits, _ = format_search_hits(docs, source_type=None, window_size=WINDOW_SIZE)
            recs = [{"pid": d[0].metadata.get("doc_id") or d[0].metadata.get("resource_id"),
                     "rank": i+1, "score": d[1]} for i, d in enumerate(hits)]
            rel = set(qrels.get(qid, {}).keys())
            sr = score_hits(recs, rel)
        except Exception as e:
            n_errors += 1
            sr = score_hits([], set(qrels.get(qid, {}).keys()))
        scores.append({"qid": qid, "query": query_text, **sr})
        n_done += 1
        if n_done % 30 == 0:
            print(f"  [{name}] {n_done}/{len(queries)} queries ({time.time()-t0:.0f}s)")

    summary = summarize(scores)
    summary["config"] = name
    summary["runtime_sec"] = round(time.time() - t0, 2)
    if n_errors:
        summary["n_errors"] = n_errors
    print(f"  [{name}] MRR@10={summary.get('MRR@10',0):.4f}  "
          f"Recall@10={summary.get('Recall@10',0):.4f}  "
          f"errors={n_errors}  time={summary['runtime_sec']:.0f}s")
    return summary


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_docs", type=int, default=MAX_DOCS)
    args = parser.parse_args()
    max_docs = args.max_docs

    print("=== T4 Chunking 2.0: loading data ===")
    docs_raw, queries, qrels = load_lecardv2(max_docs)
    print(f"  Docs: {len(docs_raw)}  Queries: {len(queries)}  Qrels: {sum(len(v) for v in qrels.values())}")

    results = {}
    for name, seps in SEPARATORS_CONFIGS.items():
        lance_dir = f"eval/experiment_lance_db_chunk_v2_{name}"
        assert "experiment" in lance_dir

        if os.path.exists(lance_dir):
            shutil.rmtree(lance_dir)
        os.makedirs(lance_dir, exist_ok=True)

        # Also clear FTS5 for this user to get clean isolation
        from backend.database import sync_engine
        try:
            with sync_engine.connect() as conn:
                conn.exec_driver_sql("DELETE FROM chunks_fts WHERE belongs_to = '10000@qq.com'")
                conn.commit()
        except Exception:
            pass

        print(f"\n--- {name} ---")
        ingest(name, seps, docs_raw, lance_dir)
        summary = await evaluate(name, lance_dir, queries, qrels)
        results[name] = summary

        out_dir = f"eval/results_chunk_v2_{name}"
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"summary_mmr_off.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    # Write comparison table
    md = "eval/ab_matrix_1.4_chunk_v2.md"
    with open(md, "w", encoding="utf-8") as f:
        f.write("# Chunking 2.0 — Separators A/B (LeCaRDv2)\n\n")
        f.write("| separators | MRR@10 | 95% CI | Recall@5 | Recall@10 | errors | runtime |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for name, s in results.items():
            ci = s.get("MRR@10_ci95", "-")
            nerr = s.get("n_errors", 0)
            f.write(f"| `{name}` | {s.get('MRR@10',0):.4f} | {ci} | "
                    f"{s.get('Recall@5',0):.4f} | {s.get('Recall@10',0):.4f} | "
                    f"{nerr} | {s.get('runtime_sec',0):.0f}s |\n")

    print(f"\n=== Done. Results saved to {md} ===")
    # Show delta
    if len(results) >= 2:
        mrr_cur = results.get("current", {}).get("MRR@10", 0)
        mrr_sem = results.get("semantic", {}).get("MRR@10", 0)
        print(f"  current MRR@10:  {mrr_cur:.4f}")
        print(f"  semantic MRR@10: {mrr_sem:.4f}")
        print(f"  delta: {mrr_sem - mrr_cur:+.4f} ({(mrr_sem/mrr_cur-1)*100:+.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
