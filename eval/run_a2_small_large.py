"""A2: Small-to-Large retrieval A/B — expand OFF vs ON on LeCaRDv2."""
import os, sys, json, time, shutil, asyncio

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
import lancedb

CHUNK_SIZE = 256
CHUNK_OVERLAP = 50
USER_ID = 1
USER_EMAIL = "10000@qq.com"
SEPARATORS = ["\n\n", "\n", "。", "，", " ", ""]

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
            if str(row.get("_id","")) in needed:
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

def ingest(docs, lance_dir):
    from backend.config import settings
    settings.CHUNK_EXPAND_ENABLED = True
    settings.CHUNK_RETRIEVAL_SIZE = CHUNK_SIZE

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
        length_function=len, separators=SEPARATORS)
    ldocs = []
    for raw in docs:
        doc_id = str(raw.get("_id",""))
        text = raw.get("text","")
        chunks = splitter.split_text(text)
        for ci, ct in enumerate(chunks):
            cid = f"{doc_id}_c{ci}"
            ldocs.append(Document(page_content=ct, metadata={
                "id": cid,
                "title": f"source=lecardv2, doc_id={doc_id}, chunk={ci}",
                "resource_id": doc_id, "doc_id": doc_id,
                "chunk_group": doc_id, "chunk_order": ci,
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
    print(f"  Ingested {len(ldocs)} chunks in {time.time()-t0:.0f}s")
    return len(ldocs)

async def evaluate(name, lance_dir, queries, qrels, expand_on):
    from backend.config import settings
    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir
    settings.CHUNK_EXPAND_ENABLED = expand_on
    settings.CHUNK_EXPAND_WINDOW = 2
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
    print("=== A2: Small-to-Large Retrieval A/B ===\n")
    docs, queries, qrels = load_subset()
    print(f"Loading: {len(docs)} docs, {len(queries)} queries\n")

    lance_dir = "eval/experiment_lance_db_a2"
    if os.path.exists(lance_dir):
        shutil.rmtree(lance_dir)
    os.makedirs(lance_dir, exist_ok=True)

    n_chunks = ingest(docs, lance_dir)

    # Run both configs
    results = {}
    for expand_on, name in [(False, "expand_off"), (True, "expand_on")]:
        results[name] = await evaluate(name, lance_dir, queries, qrels, expand_on)

    md = "eval/ab_matrix_1.5_small_large.md"
    with open(md, "w", encoding="utf-8") as f:
        f.write("# A2: Small-to-Large Retrieval (LeCaRDv2 20q, chunk_size=256)\n\n")
        f.write("| config | MRR@10 | Recall@10 | errors | runtime |\n")
        f.write("| --- | --- | --- | --- | --- |\n")
        for name, s in results.items():
            f.write(f"| `{name}` | {s.get('MRR@10',0):.4f} | {s.get('Recall@10',0):.4f} | "
                    f"{s.get('n_errors',0)} | {s.get('runtime_sec',0):.0f}s |\n")
    print(f"\n=== Done: {md} ===")
    if len(results) >= 2:
        off, on = results["expand_off"]["MRR@10"], results["expand_on"]["MRR@10"]
        print(f"Delta: expand_on vs off = {on-off:+.4f}")

if __name__ == "__main__":
    asyncio.run(main())
