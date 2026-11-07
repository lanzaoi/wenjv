import os
import sys
import csv
import json
import argparse
import asyncio

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from eval.run_eval import run_queries

CONFIGS = ["default", "hybrid_off", "rerank_on", "mmr_off"]
CSV_OUTPUT = "eval/results/ab_matrix.csv"
MD_OUTPUT = "eval/results/ab_matrix.md"

async def run_matrix(limit=None, out_dir_base="eval/results", csv_output=CSV_OUTPUT, md_output=MD_OUTPUT):
    print(f"Starting M-small Matrix evaluation across {len(CONFIGS)} configs...")
    
    summaries = []
    for cfg in CONFIGS:
        print(f"\n--- Running config: {cfg} ---")
        try:
            summary = await run_queries(cfg, limit, out_dir_base=out_dir_base)
            summary["status"] = "SUCCESS"
        except Exception as e:
            print(f"  [ERROR] Config '{cfg}' failed: {type(e).__name__}: {e}")
            summary = {
                "config": cfg,
                "MRR@10": 0.0,
                "Recall@5": 0.0,
                "Recall@10": 0.0,
                "n_queries": 0,
                "n_no_hits": 0,
                "runtime_sec": 0.0,
                "status": "FAILED",
                "error": str(e),
            }
        summaries.append(summary)
        
        # Incremental persistence: write CSV and MD after each config
        os.makedirs(os.path.dirname(csv_output), exist_ok=True)
        fieldnames = ["config", "MRR@10", "Recall@5", "Recall@10", "n_queries", "n_no_hits", "runtime_sec", "status"]
        with open(csv_output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for s in summaries:
                row = {
                    "config": s.get("config", ""),
                    "MRR@10": f"{s.get('MRR@10', 0.0):.4f}",
                    "Recall@5": f"{s.get('Recall@5', 0.0):.4f}",
                    "Recall@10": f"{s.get('Recall@10', 0.0):.4f}",
                    "n_queries": s.get("n_queries", 0),
                    "n_no_hits": s.get("n_no_hits", 0),
                    "runtime_sec": f"{s.get('runtime_sec', 0.0):.2f}",
                    "status": s.get("status", "SUCCESS"),
                }
                writer.writerow(row)
                
        with open(md_output, "w", encoding="utf-8") as f:
            f.write("# MS MARCO M-small Matrix (v1.3)\n\n")
            f.write("| Config | MRR@10 | Recall@5 | Recall@10 | n_queries | n_no_hits | runtime_sec | Status |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
            for s in summaries:
                f.write(
                    f"| `{s.get('config', '')}` | "
                    f"{s.get('MRR@10', 0.0):.4f} | "
                    f"{s.get('Recall@5', 0.0):.4f} | "
                    f"{s.get('Recall@10', 0.0):.4f} | "
                    f"{s.get('n_queries', 0)} | "
                    f"{s.get('n_no_hits', 0)} | "
                    f"{s.get('runtime_sec', 0.0):.2f} | "
                    f"{s.get('status', 'SUCCESS')} |\n"
                )
        print(f"  [FLUSHED] Updated comparison tables to {csv_output} and {md_output}")
            
    print(f"\nMatrix evaluation complete.")
    return summaries

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries per config for quick testing")
    args = parser.parse_args()
    
    asyncio.run(run_matrix(args.limit))
