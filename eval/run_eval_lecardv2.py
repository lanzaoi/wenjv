"""Run eval on LeCaRDv2 with monkeypatched LanceDB path."""
import os, sys, json, asyncio, argparse, time

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)


async def run_lecardv2(config_name, lance_dir, out_dir_base="eval/results_lecardv2"):
    from backend.api.services.search import search_documents, format_search_hits
    from backend.config import settings
    from eval.scoring import score_hits, summarize

    settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY = lance_dir

    # Force reconnect LanceDB (module-level singleton was initialized at import time)
    import lancedb as _lancedb
    import backend.vector_store.lance_db as _ldb
    _ldb.db = _lancedb.connect(lance_dir)

    with open("eval/lecardv2_data/queries.json", "r", encoding="utf-8") as f:
        queries = json.load(f)
    with open("eval/lecardv2_data/qrels.json", "r", encoding="utf-8") as f:
        qrels = json.load(f)

    t0 = time.time()

    settings.HYBRID_SEARCH_ENABLED = True
    settings.STRUCTURED_RECALL_ENABLED = True
    settings.MMR_ENABLED = True
    settings.RERANK_ENABLED = False

    if config_name == "mmr_off":
        settings.MMR_ENABLED = False
    elif config_name == "mmr_same_resource":
        settings.MMR_MODE = "same_resource"
    elif config_name.startswith("mmr_sr_lambda_"):
        settings.MMR_MODE = "same_resource"
        settings.MMR_LAMBDA = float(config_name.split("_")[-1])
    elif config_name.startswith("mmr_lambda_"):
        settings.MMR_LAMBDA = float(config_name.split("_")[-1])

    per_query_scores = []
    n_done = 0
    n_errors = 0
    for qid, query_text in queries.items():
        try:
            docs = await search_documents(
                prompt=query_text, user_email="10000@qq.com",
                window_size=10, user_id=1,
            )
            hits, _ = format_search_hits(docs, source_type=None, window_size=10)

            hit_records = []
            for rank, (doc, score, source) in enumerate(hits):
                meta = doc.metadata
                doc_id = meta.get("doc_id") or meta.get("resource_id")
                hit_records.append({"pid": doc_id, "rank": rank + 1, "score": score})

            rel_docs = set(qrels.get(qid, {}).keys())
            score_res = score_hits(hit_records, rel_docs)
        except Exception as e:
            n_errors += 1
            print(f"  [WARN] query {qid} failed: {type(e).__name__}: {str(e)[:200]}")
            score_res = score_hits([], set(qrels.get(qid, {}).keys()))
        per_query_scores.append({"qid": qid, "query": query_text, **score_res})

        n_done += 1
        if n_done % 20 == 0:
            print(f"  {n_done}/{len(queries)} queries ({time.time() - t0:.0f}s)")

    summary = summarize(per_query_scores)
    summary["config"] = config_name
    summary["runtime_sec"] = round(time.time() - t0, 2)
    if n_errors:
        summary["n_errors"] = n_errors
        print(f"  [{n_errors}/{len(queries)} queries had errors, scored as zero]")

    os.makedirs(out_dir_base, exist_ok=True)
    out_file = os.path.join(out_dir_base, f"summary_{config_name}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Saved {out_file}: MRR@10={summary.get('MRR@10', 0):.4f}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True,
                        choices=["mmr_off", "mmr_same_resource", "mmr_sr_lambda_0.9",
                                 "mmr_lambda_0.9", "mmr_lambda_0.7"])
    parser.add_argument("--lance_dir", type=str,
                        default="eval/experiment_lance_db_lecardv2")
    args = parser.parse_args()
    asyncio.run(run_lecardv2(args.config, args.lance_dir))
