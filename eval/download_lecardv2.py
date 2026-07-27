"""Download LeCaRDv2 (MTEB) from HuggingFace for Chinese document-level eval."""
import os, sys, json

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

DATA_DIR = "eval/lecardv2_data"


def download():
    os.makedirs(DATA_DIR, exist_ok=True)

    from datasets import load_dataset, get_dataset_split_names
    print("Available splits:", get_dataset_split_names("mteb/LeCaRDv2"))

    # MTEB format: corpus, queries, default (qrels)
    corpus = load_dataset("mteb/LeCaRDv2", "corpus", split="train")
    queries = load_dataset("mteb/LeCaRDv2", "queries", split="train")
    qrels_ds = load_dataset("mteb/LeCaRDv2", "default", split="test")

    # Save corpus
    corpus_path = os.path.join(DATA_DIR, "corpus.jsonl")
    with open(corpus_path, "w", encoding="utf-8") as f:
        for row in corpus:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Saved {len(corpus)} docs to {corpus_path}")

    # Save queries
    queries_path = os.path.join(DATA_DIR, "queries.json")
    qmap = {}
    for row in queries:
        qmap[row.get("_id", row.get("id", str(len(qmap))))] = row.get(
            "text", row.get("query", "")
        )
    with open(queries_path, "w", encoding="utf-8") as f:
        json.dump(qmap, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(qmap)} queries to {queries_path}")

    # Save qrels
    qrels_path = os.path.join(DATA_DIR, "qrels.json")
    qr = {}
    for row in qrels_ds:
        qid = str(row.get("query-id", row.get("qid", "")))
        did = str(row.get("corpus-id", row.get("docid", row.get("_id", ""))))
        score = int(row.get("score", 1))
        qr.setdefault(qid, {})[did] = score
    with open(qrels_path, "w", encoding="utf-8") as f:
        json.dump(qr, f, ensure_ascii=False, indent=2)
    print(f"Saved qrels ({sum(len(v) for v in qr.values())} pairs) to {qrels_path}")


if __name__ == "__main__":
    download()
