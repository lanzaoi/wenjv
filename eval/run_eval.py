import json
import os
import sys
import argparse
import time

# Ensure project root on path
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

import asyncio

def load_sample(limit=None):
    with open("eval/sample_1000.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    if limit:
        data = data[:limit]
    return data

async def run_queries(config_name, limit, out_dir_base="eval/results"):
    from backend.api.services.search import search_documents, format_search_hits
    from backend.config import settings
    
    t0 = time.time()
    
    # Reset to default baseline first
    settings.HYBRID_SEARCH_ENABLED = True
    settings.STRUCTURED_RECALL_ENABLED = True
    settings.MMR_ENABLED = True
    settings.RERANK_ENABLED = False
    
    # Configure via monkeypatch
    if config_name == "default":
        pass
    elif config_name == "hybrid_off":
        settings.HYBRID_SEARCH_ENABLED = False
    elif config_name == "rerank_on":
        settings.RERANK_ENABLED = True
    elif config_name == "mmr_off":
        settings.MMR_ENABLED = False
    elif config_name.startswith("mmr_lambda_"):
        lambda_val = float(config_name.split("_")[-1])
        settings.MMR_ENABLED = True
        settings.MMR_LAMBDA = lambda_val
    elif config_name == "mmr_same_resource":
        settings.MMR_ENABLED = True
        settings.MMR_MODE = "same_resource"
    elif config_name.startswith("mmr_sr_lambda_"):
        lambda_val = float(config_name.split("_")[-1])
        settings.MMR_ENABLED = True
        settings.MMR_MODE = "same_resource"
        settings.MMR_LAMBDA = lambda_val
        
    print(f"Running eval with config '{config_name}' (limit={limit})")
    
    data = load_sample(limit)
    out_dir = os.path.join(out_dir_base, f"config_{config_name}")
    os.makedirs(out_dir, exist_ok=True)
    
    from eval.scoring import score_hits, summarize
    
    results = []
    per_query_scores = []
    
    for item in data:
        qid = item["qid"]
        query = item["query"]
        rel_pids = set(item.get("relevant_pids", []))
        
        docs = await search_documents(
            prompt=query,
            user_email="10000@qq.com",
            window_size=10,
            user_id=1,
        )
        
        # Format hits
        hits, _ = format_search_hits(docs, source_type=None, window_size=10)
        
        hit_records = []
        for rank, (doc, score, source) in enumerate(hits):
            meta = doc.metadata
            # Extract pid from title "source=msmarco, pid=123"
            title = (meta.get("title") or meta.get("filename") or "").strip()
            pid = None
            if "pid=" in title:
                pid = title.split("pid=")[-1].split(",")[0].strip()
            elif "MSMARCO_" in title:
                pid = title.split("MSMARCO_")[-1].strip()
                
            hit_records.append({
                "pid": pid,
                "rank": rank + 1,
                "chunk_id": doc.id if hasattr(doc, "id") else None,
                "score": score
            })
            
        results.append({
            "qid": qid,
            "query": query,
            "hits": hit_records
        })
        
        score_res = score_hits(hit_records, rel_pids)
        per_query_scores.append({
            "qid": qid,
            "query": query,
            **score_res
        })
        
    out_file = os.path.join(out_dir, "raw_hits.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    per_query_file = os.path.join(out_dir, "per_query.json")
    with open(per_query_file, "w", encoding="utf-8") as f:
        json.dump(per_query_scores, f, indent=2, ensure_ascii=False)
        
    summary_data = summarize(per_query_scores)
    summary_data["config"] = config_name
    summary_data["runtime_sec"] = round(time.time() - t0, 2)
    summary_file = os.path.join(out_dir, "summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)
        
    print(f"Saved raw hits to {out_file}")
    print(f"Saved per-query scores to {per_query_file}")
    print(f"Saved summary to {summary_file}: {summary_data}")
    return summary_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True,
        choices=["default", "hybrid_off", "rerank_on", "mmr_off",
                 "mmr_lambda_0.7", "mmr_lambda_0.8", "mmr_lambda_0.85",
                 "mmr_lambda_0.9", "mmr_lambda_0.95", "mmr_lambda_1.0",
                 "mmr_same_resource", "mmr_sr_lambda_0.7", "mmr_sr_lambda_0.9"])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    
    asyncio.run(run_queries(args.config, args.limit))
