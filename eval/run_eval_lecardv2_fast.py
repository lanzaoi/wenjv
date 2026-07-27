"""Fast eval runner for LeCaRDv2 subset."""
import os, sys, json, asyncio, argparse, time

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)


async def run_fast(config_name, lance_dir, n_queries=20):
    from backend.api.services.search import search_documents, format_search_hits
    from backend.config import settings
    from eval.scoring import score_hits, summarize

    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir
    import lancedb, backend.vector_store.lance_db as ldb
    ldb.db = lancedb.connect(lance_dir)

    with open("eval/lecardv2_data/queries_subset.json", "r", encoding="utf-8") as f:
        all_queries = json.load(f)
    queries = dict(list(all_queries.items())[:n_queries])
    with open("eval/lecardv2_data/qrels_subset.json", "r", encoding="utf-8") as f:
        all_qrels = json.load(f)
    qrels = {k: all_qrels[k] for k in queries if k in all_qrels}

    print(f"Eval: {len(queries)} queries, {sum(len(v) for v in qrels.values())} qrel pairs")

    t0 = time.time()
    settings.HYBRID_SEARCH_ENABLED = True
    settings.STRUCTURED_RECALL_ENABLED = True
    settings.MMR_ENABLED = False
    settings.RERANK_ENABLED = False

    if config_name == "mmr_same_resource":
        settings.MMR_ENABLED = True
        settings.MMR_MODE = "same_resource"
        settings.MMR_LAMBDA = 0.85
    elif config_name == "mmr_standard":
        settings.MMR_ENABLED = True
        settings.MMR_LAMBDA = 0.85
    elif config_name == "mmr_lambda_0.85":
        settings.MMR_ENABLED = True
        settings.MMR_LAMBDA = 0.85

    scores = []
    n_err = 0
    for qid, qtext in queries.items():
        try:
            docs = await search_documents(prompt=qtext, user_email="10000@qq.com", window_size=10, user_id=1)
            hits, _ = format_search_hits(docs, source_type=None, window_size=10)
            recs = [{"pid": d[0].metadata.get("resource_id", ""), "rank": i+1, "score": d[1]} for i, d in enumerate(hits)]
            rel = set(qrels.get(qid, {}).keys())
            sr = score_hits(recs, rel)
        except Exception as e:
            n_err += 1
            sr = score_hits([], set(qrels.get(qid, {}).keys()))
        scores.append({"qid": qid, "query": qtext, **sr})

    summary = summarize(scores)
    summary["config"] = config_name
    summary["runtime_sec"] = round(time.time() - t0, 2)
    if n_err:
        summary["n_errors"] = n_err

    os.makedirs("eval/results_lecardv2_fast", exist_ok=True)
    out = os.path.join("eval/results_lecardv2_fast", f"summary_{config_name}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"  {config_name}: MRR@10={summary.get('MRR@10',0):.4f}  Recall@10={summary.get('Recall@10',0):.4f}  errors={n_err}  time={summary['runtime_sec']:.0f}s")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, choices=["mmr_off", "mmr_standard", "mmr_same_resource", "mmr_lambda_0.85"])
    parser.add_argument("--lance_dir", type=str, default="eval/experiment_lance_db_lecardv2")
    parser.add_argument("--n_queries", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(run_fast(args.config, args.lance_dir, args.n_queries))
