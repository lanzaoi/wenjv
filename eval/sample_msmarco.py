import os
import json
import random

DATA_DIR = "eval/msmarco_data"
QRELS_FILE = os.path.join(DATA_DIR, "qrels.dev.small.tsv")
QUERIES_FILE = os.path.join(DATA_DIR, "queries.dev.small.tsv")
if not os.path.exists(QUERIES_FILE):
    QUERIES_FILE = os.path.join(DATA_DIR, "queries.dev.tsv")
COLLECTION_FILE = os.path.join(DATA_DIR, "collection.tsv")
OUTPUT_FILE = "eval/sample_1000.json"

def main():
    # 1. Load qrels
    qrels = {}
    if not os.path.exists(QRELS_FILE):
        print(f"Error: {QRELS_FILE} not found. Run download_msmarco.py first.")
        return
        
    with open(QRELS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t", 3)
            if len(parts) >= 4:
                qid, _, pid, rel = parts
                if int(rel) > 0:
                    qrels.setdefault(qid, set()).add(pid)
    
    # 2. Load queries
    queries = {}
    with open(QUERIES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) >= 2:
                qid, text = parts[0], parts[1]
                if qid in qrels:
                    queries[qid] = text

    # 3. Sample 1000 queries
    random.seed(42)
    sampled_qids = random.sample(list(queries.keys()), min(1000, len(queries)))
    
    needed_pids = set()
    for qid in sampled_qids:
        needed_pids.update(qrels[qid])
        
    # 4. Extract passages from collection.tsv
    passages = {}
    print(f"Scanning collection.tsv for {len(needed_pids)} PIDs...")
    with open(COLLECTION_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) >= 2:
                pid, text = parts[0], parts[1]
                if pid in needed_pids:
                    passages[pid] = text
                    if len(passages) == len(needed_pids):
                        break  # Found all needed PIDs

    # 5. Build output format
    output_data = []
    total_reldocs = 0
    for qid in sampled_qids:
        rel_pids = list(qrels[qid])
        rel_passages = [passages[pid] for pid in rel_pids if pid in passages]
        output_data.append({
            "qid": qid,
            "query": queries[qid],
            "relevant_pids": rel_pids,
            "relevant_passages": rel_passages
        })
        total_reldocs += len(rel_passages)
        
    # 6. Save
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        
    # 7. Statistics
    print(f"Total Queries: {len(output_data)}")
    print(f"Total Unique Passages: {len(passages)}")
    print(f"Avg RelDocs per Query: {total_reldocs / len(output_data):.2f}")

if __name__ == "__main__":
    main()
