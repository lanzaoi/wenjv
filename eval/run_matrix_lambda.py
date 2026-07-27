"""Run MMR lambda grid search across 7 configs on MS MARCO passage data."""
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

LAMBDA_CONFIGS = [
    "mmr_off",
    "mmr_lambda_0.7",
    "mmr_lambda_0.8",
    "mmr_lambda_0.85",
    "mmr_lambda_0.9",
    "mmr_lambda_0.95",
    "mmr_lambda_1.0",
]
CSV_OUTPUT = "eval/ab_matrix_1.4_lambda.csv"
MD_OUTPUT = "eval/ab_matrix_1.4_lambda.md"


async def run_matrix(limit=None, out_dir_base="eval/results"):
    print(f"Starting MMR Lambda Grid across {len(LAMBDA_CONFIGS)} configs...")

    summaries = []
    for cfg in LAMBDA_CONFIGS:
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

        # Incremental flush
        _write_outputs(summaries)

    print("\nLambda grid complete.")
    # Sanity check: mmr_lambda_1.0 should ≈ mmr_off
    mmr_off_mrr = None
    mmr_l1_mrr = None
    for s in summaries:
        if s["config"] == "mmr_off":
            mmr_off_mrr = s.get("MRR@10", 0)
        if s["config"] == "mmr_lambda_1.0":
            mmr_l1_mrr = s.get("MRR@10", 0)
    if mmr_off_mrr is not None and mmr_l1_mrr is not None:
        diff = abs(mmr_off_mrr - mmr_l1_mrr)
        if diff > 0.02:
            print(f"\n⚠️  SANITY CHECK FAILED: mmr_off={mmr_off_mrr:.4f}, "
                  f"mmr_lambda_1.0={mmr_l1_mrr:.4f}, diff={diff:.4f} > 0.02")
        else:
            print(f"\n✅ Sanity check passed: diff={diff:.4f}")

    return summaries


def _write_outputs(summaries):
    os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)
    fieldnames = [
        "config", "MRR@10", "Recall@5", "Recall@10",
        "n_queries", "n_no_hits", "runtime_sec", "status",
    ]
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for s in summaries:
            writer.writerow({
                "config": s.get("config", ""),
                "MRR@10": f"{s.get('MRR@10', 0.0):.4f}",
                "Recall@5": f"{s.get('Recall@5', 0.0):.4f}",
                "Recall@10": f"{s.get('Recall@10', 0.0):.4f}",
                "n_queries": s.get("n_queries", 0),
                "n_no_hits": s.get("n_no_hits", 0),
                "runtime_sec": f"{s.get('runtime_sec', 0.0):.2f}",
                "status": s.get("status", "SUCCESS"),
            })

    with open(MD_OUTPUT, "w", encoding="utf-8") as f:
        f.write("# MMR Lambda Grid (MS MARCO)\n\n")
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
    print(f"  [FLUSHED] {CSV_OUTPUT} and {MD_OUTPUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run_matrix(args.limit))
