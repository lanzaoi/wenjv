"""A3: Late Chunking A/B — regular vs late chunking on LeCaRDv2."""
import os, sys, json, time, shutil, asyncio

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
import lancedb

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150
USER_ID = 1
USER_EMAIL = "10000@qq.com"

def load_subset():
    with open("eval/lecardv2_data/qrels.json", encoding="utf-8") as f:
        qrels_all = json.load(f)
    qids = list(qrels_all.keys())[:20]
    needed = set()
    for qid in qids:
        needed.update(qrels_all[qid].keys())
    with open("eval/lecardv2_data/corpus.jsonl", encoding="utf-8") as f:
        relevant, distractors = [], []
        for line in f:
            row = json.loads(line)
            if str(row.get("_id","")) in needed: relevant.append(row)
            else: distractors.append(row)
    import random; random.seed(42)
    dist = random.sample(distractors, min(50, len(distractors)))
    with open("eval/lecardv2_data/queries.json", encoding="utf-8") as f:
        queries_all = json.load(f)
    queries = {str(qid): queries_all[str(qid)] for qid in qids if str(qid) in queries_all}
    qrels = {qid: qrels_all[qid] for qid in qids}
    return relevant + dist, queries, qrels

def ingest(docs, lance_dir, late_chunking):
    from backend.config import settings
    settings.LATE_CHUNKING_ENABLED = late_chunking

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
        length_function=len, separators=["\n\n", "\n", "。", "，", " ", ""])
    ldocs = []
    for raw in docs:
        doc_id = str(raw.get("_id",""))
        for ci, ct in enumerate(splitter.split_text(raw.get("text",""))):
            ldocs.append(Document(page_content=ct, metadata={
                "title": f"source=lecardv2, doc_id={doc_id}, chunk={ci}",
                "resource_id": doc_id, "doc_id": doc_id,
                "belongs_to": USER_EMAIL, "user_id": str(USER_ID),
                "source_type": "note", "source": "lecardv2"}))

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
    print(f"  Ingested {len(ldocs)} chunks in {time.time()-t0:.0f}s (late={late_chunking})")
    return len(ldocs)

async def evaluate(name, lance_dir, queries, qrels, late_on):
    from backend.config import settings
    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir
    settings.LATE_CHUNKING_ENABLED = late_on
    settings.LATE_CHUNKING_TOP_DOCS = 5
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
    if n_err: s["n_errors"] = n_err
    print(f"  [{name}] MRR@10={s.get('MRR@10',0):.4f} Recall@10={s.get('Recall@10',0):.4f} errors={n_err} time={s['runtime_sec']:.0f}s")
    return s

async def main():
    print("=== A3: Late Chunking A/B ===\n")
    docs, queries, qrels = load_subset()
    print(f"Loading: {len(docs)} docs, {len(queries)} queries\n")

    results = {}
    for late, name in [(False, "standard"), (True, "late_chunking")]:
        lance_dir = f"eval/experiment_lance_db_a3_{name}"
        if os.path.exists(lance_dir): shutil.rmtree(lance_dir)
        os.makedirs(lance_dir, exist_ok=True)
        ingest(docs, lance_dir, late)
        results[name] = await evaluate(name, lance_dir, queries, qrels, late)

    md = "eval/ab_matrix_1.5_late_chunking.md"
    with open(md, "w", encoding="utf-8") as f:
        f.write("# A3: Late Chunking A/B (LeCaRDv2 20q)\n\n")
        f.write("| config | MRR@10 | Recall@10 | errors | runtime |\n")
        f.write("| --- | --- | --- | --- | --- |\n")
        for name, s in results.items():
            f.write(f"| `{name}` | {s.get('MRR@10',0):.4f} | {s.get('Recall@10',0):.4f} | "
                    f"{s.get('n_errors',0)} | {s.get('runtime_sec',0):.0f}s |\n")
    print(f"\n=== Done: {md} ===")

if __name__ == "__main__":
    asyncio.run(main())
