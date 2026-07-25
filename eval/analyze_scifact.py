import json, sys

BASE = "C:/Users/Lanzao/Downloads/scifact/scifact"

qrels = {}
with open(f"{BASE}/qrels/test.tsv") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('query-id'):
            continue
        parts = line.split('\t')
        qid, cid = parts[0], parts[1]
        qrels.setdefault(qid, []).append(cid)

queries = {}
with open(f"{BASE}/queries.jsonl") as f:
    for line in f:
        q = json.loads(line)
        queries[q['_id']] = q['text']

corpus = {}
with open(f"{BASE}/corpus.jsonl") as f:
    for line in f:
        doc = json.loads(line)
        corpus[doc['_id']] = doc

test_qids = [qid for qid in qrels if qid in queries]
relevant_doc_ids = set()
for cids in qrels.values():
    relevant_doc_ids.update(cids)

print(f"=== SciFact Test Set ===")
print(f"Queries with answers: {len(qrels)}")
print(f"Total qrels rows:     {sum(len(v) for v in qrels.values())}")
print(f"Queries with text:    {len(test_qids)}")
print(f"Relevant docs:        {len(relevant_doc_ids)}")
print(f"Corpus total:         {len(corpus)}")

print(f"\n=== Sample Q&A ===")
for qid in test_qids[:3]:
    print(f"\nQ{qid}: {queries[qid]}")
    for cid in qrels[qid][:2]:
        if cid in corpus:
            print(f"  A: [{corpus[cid]['title'][:80]}]")
