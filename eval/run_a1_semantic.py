"""A1: Semantic chunking A/B — current vs semantic separators on LeCaRDv2."""
import os, sys, json, time, shutil, asyncio

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
import lancedb

MAX_DOCS = None  # all relevant docs for 20 queries
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150
USER_ID = 1
USER_EMAIL = "10000@qq.com"

CONFIGS = {
    "current":  ["\n\n", "\n", "。", "，", " ", ""],
    "semantic": ["\n\n", "。", "！", "？", "；"],
}

def load_subset():
    with open("eval/lecardv2_data/qrels.json", encoding="utf-8") as f:
        qrels_all = json.load(f)
    qids = list(qrels_all.keys())[:20]
    needed = set()
    for qid in qids:
        needed.update(qrels_all[qid].keys())

    with open("eval/lecardv2_data/corpus.jsonl", encoding="utf-8") as f:
        relevant = []
        distractors = []
        for line in f:
            row = json.loads(line)
            doc_id = str(row.get("_id", ""))
            if doc_id in needed:
                relevant.append(row)
            else:
                distractors.append(row)

    import random; random.seed(42)
    dist = random.sample(distractors, min(50, len(distractors)))
    all_docs = relevant + dist

    with open("eval/lecardv2_data/queries.json", encoding="utf-8") as f:
        queries_all = json.load(f)
    queries = {str(qid): queries_all[str(qid)] for qid in qids if str(qid) in queries_all}
    qrels = {qid: qrels_all[qid] for qid in qids}

    return all_docs, queries, qrels

def ingest(name, seps, docs, lance_dir):
    print(f"  [{name}] chunking {len(docs)} docs...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
        length_function=len, separators=seps)
    ldocs = []
    for raw in docs:
        doc_id = str(raw.get("_id", ""))
        chunks = splitter.split_text(raw.get("text", ""))
        for ci, ct in enumerate(chunks):
            ldocs.append(Document(page_content=ct, metadata={
                "title": f"source=lecardv2, doc_id={doc_id}, chunk={ci}",
                "resource_id": doc_id, "doc_id": doc_id, "chunk_idx": ci,
                "belongs_to": USER_EMAIL, "user_id": str(USER_ID),
                "source_type": "note", "source": "lecardv2"}))

    from backend.config import settings
    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir
    import backend.vector_store.lance_db as ldb
    ldb.db = lancedb.connect(lance_dir)
    if settings.VECTOR_STORE_COLLECTION_NAME not in ldb.db.table_names():
        ldb.initialize_collection()

    from backend.vector_store.lance_db import add_documents
    BATCH = 100
    t0 = time.time()
    for i in range(0, len(ldocs), BATCH):
        add_documents(ldocs[i:i+BATCH])
    elapsed = time.time() - t0
    print(f"  [{name}] {len(ldocs)} chunks in {elapsed:.0f}s")
    return len(ldocs)

async def evaluate(name, lance_dir, queries, qrels):
    from backend.config import settings
    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir
    import backend.vector_store.lance_db as ldb
    ldb.db = lancedb.connect(lance_dir)

    from backend.api.services.search import search_documents, format_search_hits
    from eval.scoring import score_hits, summarize

    settings.HYBRID_SEARCH_ENABLED = True
    settings.STRUCTURED_RECALL_ENABLED = True
    settings.MMR_ENABLED = False
    settings.RERANK_ENABLED = False

    t0 = time.time()
    scores = []
    n_err = 0
    for qid, qtext in queries.items():
        try:
            docs = await search_documents(prompt=qtext, user_email=USER_EMAIL, window_size=10, user_id=USER_ID)
            hits, _ = format_search_hits(docs, source_type=None, window_size=10)
            recs = [{"pid": d[0].metadata.get("resource_id",""), "rank": i+1, "score": d[1]} for i,d in enumerate(hits)]
            sr = score_hits(recs, set(qrels.get(qid, {}).keys()))
        except Exception as e:
            n_err += 1
            sr = score_hits([], set(qrels.get(qid, {}).keys()))
        scores.append({"qid": qid, **sr})

    s = summarize(scores)
    s["config"] = name
    s["runtime_sec"] = round(time.time()-t0, 2)
    s["chunks"] = 0  # filled below
    if n_err: s["n_errors"] = n_err
    print(f"  [{name}] MRR@10={s.get('MRR@10',0):.4f} Recall@10={s.get('Recall@10',0):.4f} ci={s.get('MRR@10_ci95','?')} errors={n_err} time={s['runtime_sec']:.0f}s")
    return s

async def main():
    print("=== A1: Semantic Chunking A/B ===\n")
    docs, queries, qrels = load_subset()
    print(f"Loading: {len(docs)} docs, {len(queries)} queries, {sum(len(v) for v in qrels.values())} qrel pairs\n")

    results = {}
    for name, seps in CONFIGS.items():
        lance_dir = f"eval/experiment_lance_db_a1_{name}"
        assert "experiment" in lance_dir
        if os.path.exists(lance_dir):
            shutil.rmtree(lance_dir)
        os.makedirs(lance_dir, exist_ok=True)

        n_chunks = ingest(name, seps, docs, lance_dir)
        summary = await evaluate(name, lance_dir, queries, qrels)
        summary["chunks"] = n_chunks
        results[name] = summary

    # Write output
    md = "eval/ab_matrix_1.5_chunk_semantic.md"
    with open(md, "w", encoding="utf-8") as f:
        f.write("# A1: Semantic Chunking A/B (LeCaRDv2 20q)\n\n")
        f.write("| config | MRR@10 | 95% CI | Recall@10 | chunks | runtime |\n")
        f.write("| --- | --- | --- | --- | --- | --- |\n")
        for name, s in results.items():
            f.write(f"| `{name}` | {s.get('MRR@10',0):.4f} | {s.get('MRR@10_ci95','-')} | "
                    f"{s.get('Recall@10',0):.4f} | {s.get('chunks',0)} | {s.get('runtime_sec',0):.0f}s |\n")

    print(f"\n=== Done: {md} ===")
    if len(results) >= 2:
        cur, sem = results["current"]["MRR@10"], results["semantic"]["MRR@10"]
        print(f"Delta: semantic vs current = {sem-cur:+.4f}")

if __name__ == "__main__":
    asyncio.run(main())
