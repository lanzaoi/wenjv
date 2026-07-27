"""Chunking grid search on LeCaRDv2.

For each chunk_size in {512, 1000, 1500, 2000}:
  1. Re-ingest with new chunk_size to isolated LanceDB dir
  2. Run eval with given config
  3. Save summary with bootstrap CI
"""
import os, sys, asyncio, argparse, shutil, json, glob

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

CHUNK_GRID = [512, 1000, 1500, 2000]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="mmr_off",
                        help="Eval config to use")
    parser.add_argument("--max_docs", type=int, default=1000,
                        help="Docs per grid point")
    args = parser.parse_args()

    summaries = []
    for cs in CHUNK_GRID:
        overlap = max(50, cs // 10)
        lance_dir = f"eval/experiment_lance_db_chunk_{cs}"
        assert "experiment" in lance_dir

        print(f"\n{'='*60}")
        print(f"Chunk Size: {cs}, Overlap: {overlap}")
        print(f"{'='*60}")

        # Clear old dir
        if os.path.exists(lance_dir):
            shutil.rmtree(lance_dir)
        os.makedirs(lance_dir, exist_ok=True)

        # Re-ingest
        import subprocess

        ingest_cmd = [
            sys.executable, "eval/ingest_lecardv2.py",
            "--max_docs", str(args.max_docs),
            "--chunk_size", str(cs),
            "--chunk_overlap", str(overlap),
            "--lance_dir", lance_dir,
        ]
        result = subprocess.run(ingest_cmd, capture_output=True, text=True)
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
        if result.returncode != 0:
            print(f"  [ERROR] Ingest failed: {result.stderr[-300:]}")
            summaries.append({"chunk_size": cs, "chunk_overlap": overlap,
                              "MRR@10": 0, "Recall@10": 0, "status": "INGEST_FAILED"})
            continue

        # Run eval
        eval_cmd = [
            sys.executable, "eval/run_eval_lecardv2.py",
            "--config", args.config,
            "--lance_dir", lance_dir,
        ]
        result = subprocess.run(eval_cmd, capture_output=True, text=True)
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
        if result.returncode != 0:
            print(f"  [ERROR] Eval failed: {result.stderr[-300:]}")
            summaries.append({"chunk_size": cs, "chunk_overlap": overlap,
                              "MRR@10": 0, "Recall@10": 0, "status": "EVAL_FAILED"})
            continue

        # Read summary
        summary_files = glob.glob(f"eval/results_lecardv2/summary_{args.config}.json")
        if summary_files:
            with open(summary_files[0], "r") as f:
                s = json.load(f)
            s["chunk_size"] = cs
            s["chunk_overlap"] = overlap
            s["status"] = "SUCCESS"
            summaries.append(s)
            print(f"  MRR@10={s.get('MRR@10', 0):.4f}, "
                  f"Recall@10={s.get('Recall@10', 0):.4f}")
        else:
            summaries.append({"chunk_size": cs, "chunk_overlap": overlap,
                              "MRR@10": 0, "Recall@10": 0, "status": "NO_OUTPUT"})

    # Output table
    md_path = "eval/ab_matrix_1.4_chunk.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Chunking Grid (LeCaRDv2)\n\n")
        f.write("| chunk_size | overlap | MRR@10 | 95% CI | Recall@10 | status |\n")
        f.write("| --- | --- | --- | --- | --- | --- |\n")
        for s in summaries:
            ci = s.get("MRR@10_ci95", "-")
            f.write(
                f"| {s.get('chunk_size', '?')} | {s.get('chunk_overlap', '?')} | "
                f"{s.get('MRR@10', 0):.4f} | {ci} | "
                f"{s.get('Recall@10', 0):.4f} | {s.get('status', '?')} |\n"
            )
    print(f"\nSaved {md_path}")

    # Show best
    success = [s for s in summaries if s.get("status") == "SUCCESS"]
    if success:
        best = max(success, key=lambda s: s.get("MRR@10", 0))
        print(f"\nBest: chunk_size={best['chunk_size']}, "
              f"MRR@10={best.get('MRR@10', 0):.4f}")


if __name__ == "__main__":
    asyncio.run(main())
