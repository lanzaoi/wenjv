#!/usr/bin/env python3
"""
eval/run_spark_55_benchmark.py

End-to-End Multimodal RAG Benchmark Runner targeting iFLYTEK Spark-X2.6.
Executes all 55 picked ArXiv queries through dual-store LanceDB retrieval +
BGE-M3/SigLIP-2 fusion + BGE Cross-Encoder reranking + Spark-X2.6 generation.
Outputs atomic checkpoints to eval/results/spark_e2e_benchmark_checkpoint.json.
"""
from __future__ import annotations

import socket

_orig_getaddrinfo = socket.getaddrinfo


def enable_ipv4_socket_pinning() -> None:
    """Force IPv4 address resolution to prevent WSL2 dual-stack routing hangs."""
    if getattr(socket, "_is_ipv4_pinned", False):
        return

    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_getaddrinfo
    socket._is_ipv4_pinned = True


enable_ipv4_socket_pinning()

import argparse
import asyncio
from datetime import datetime, timezone
import gc
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings
from backend.api.services.chat import rag_chat_events
from tests.test_benchmark_pipeline import validate_checkpoint_entry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("spark_benchmark")

DATA_DIR = PROJECT_ROOT / "eval" / "eval" / "open_ragbench_data"
DEFAULT_CHECKPOINT_PATH = PROJECT_ROOT / "eval" / "results" / "spark_e2e_benchmark_checkpoint.json"

DEFAULT_PACING_DELAY = 2.0  # seconds between queries
EVAL_USER_EMAIL = "tester_e2e@wenjv.internal"
EVAL_USER_ID = 9999
EVAL_WINDOW_SIZE = 5
PRIMARY_MODEL = "spark-x2.6"


def load_benchmark_dataset(
    data_dir: Path,
) -> Tuple[List[str], Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    picked_path = data_dir / "picked_qids.json"
    queries_path = data_dir / "pdf" / "arxiv" / "queries.json"
    answers_path = data_dir / "pdf" / "arxiv" / "answers.json"
    qrels_path = data_dir / "pdf" / "arxiv" / "qrels.json"

    with open(picked_path, "r", encoding="utf-8") as f:
        picked_qids: List[str] = json.load(f)
    with open(queries_path, "r", encoding="utf-8") as f:
        queries: Dict[str, Any] = json.load(f)
    with open(answers_path, "r", encoding="utf-8") as f:
        answers: Dict[str, str] = json.load(f)
    with open(qrels_path, "r", encoding="utf-8") as f:
        qrels: Dict[str, Any] = json.load(f)

    if len(picked_qids) != 55:
        raise ValueError(f"Expected 55 picked queries, got {len(picked_qids)}")

    return picked_qids, queries, answers, qrels


def load_existing_checkpoint(checkpoint_path: Path) -> List[Dict[str, Any]]:
    if not checkpoint_path.exists():
        return []
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            valid_entries = []
            for entry in data:
                try:
                    validate_checkpoint_entry(entry)
                    valid_entries.append(entry)
                except Exception as ve:
                    logger.warning(f"Skipping invalid checkpoint entry {entry.get('qid')}: {ve}")
            return valid_entries
    except Exception as exc:
        logger.warning(f"Could not read existing checkpoint at {checkpoint_path} ({exc}), starting fresh.")
    return []


def save_checkpoint_atomic(checkpoint_path: Path, entries: List[Dict[str, Any]]) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = checkpoint_path.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, checkpoint_path)


def clean_citations(raw_citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = []
    for i, cit in enumerate(raw_citations, start=1):
        has_image = bool(cit.get("has_image", False))
        img_path = cit.get("image_path")
        cleaned.append({
            "index": int(cit.get("index", i)),
            "source": str(cit.get("source", "")),
            "title": str(cit.get("title", "") or cit.get("filename", "")),
            "page": str(cit.get("page", "")),
            "score": round(float(cit.get("score", 0.0)), 4),
            "snippet": str(cit.get("snippet", ""))[:400],
            "has_image": has_image,
            "image_path": str(img_path) if img_path else None,
        })
    return cleaned


def count_visual_evidence(citations: List[Dict[str, Any]]) -> int:
    return min(
        3,
        sum(
            1
            for c in citations
            if c.get("has_image") and c.get("image_path") and os.path.exists(str(c["image_path"]))
        ),
    )


async def execute_query_single_attempt(
    *,
    query_text: str,
    target_model: str,
    timeout_sec: float = 120.0,
) -> Dict[str, Any]:
    settings.CHAT_MODEL = target_model
    tokens: List[str] = []
    raw_citations: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    t_start = time.perf_counter()
    t_citations: Optional[float] = None

    async def _consume():
        nonlocal t_citations, raw_citations, tokens, error_msg
        async for ev in rag_chat_events(
            question=query_text,
            user_email=EVAL_USER_EMAIL,
            user_id=EVAL_USER_ID,
            window_size=EVAL_WINDOW_SIZE,
            use_rag=True,
        ):
            ev_type = ev.get("type")
            if ev_type == "citations":
                t_citations = time.perf_counter()
                raw_citations = ev.get("citations", [])
            elif ev_type == "token":
                content = ev.get("content", "")
                if content:
                    tokens.append(content)
            elif ev_type == "error":
                error_msg = ev.get("message")
            elif ev_type == "done":
                pass

    await asyncio.wait_for(_consume(), timeout=timeout_sec)

    t_end = time.perf_counter()
    if t_citations is None:
        t_citations = t_start

    retrieval_ms = max(0.0, (t_citations - t_start) * 1000.0)
    generation_ms = max(0.0, (t_end - t_citations) * 1000.0)
    total_ms = max(0.0, (t_end - t_start) * 1000.0)

    if error_msg:
        raise RuntimeError(f"rag_chat_events reported error: {error_msg}")

    generated_answer = "".join(tokens).strip()
    if not generated_answer:
        raise RuntimeError("Empty response received from rag_chat_events generator")

    return {
        "generated_answer": generated_answer,
        "raw_citations": raw_citations,
        "timings": {
            "retrieval_ms": round(retrieval_ms, 2),
            "generation_ms": round(generation_ms, 2),
            "total_ms": round(total_ms, 2),
        },
    }


async def run_benchmark(
    *,
    limit: Optional[int] = None,
    pacing_delay: float = DEFAULT_PACING_DELAY,
    checkpoint_file: Path = DEFAULT_CHECKPOINT_PATH,
    resume: bool = True,
) -> None:
    settings.QUERY_CACHE_ENABLED = False

    picked_qids, queries, answers, qrels = load_benchmark_dataset(DATA_DIR)

    existing_entries: List[Dict[str, Any]] = []
    completed_qids: Set[str] = set()
    if resume:
        existing_entries = load_existing_checkpoint(checkpoint_file)
        completed_qids = {e["qid"] for e in existing_entries}
        logger.info(f"Loaded {len(completed_qids)} completed queries from checkpoint: {checkpoint_file}")

    target_qids = picked_qids[:limit] if limit is not None else picked_qids
    remaining_qids = [q for q in target_qids if q not in completed_qids]

    logger.info("=" * 80)
    logger.info("Spark-X2.6 Benchmark Configuration:")
    logger.info(f"  Target Queries: {len(target_qids)} | Completed: {len(completed_qids)} | Remaining: {len(remaining_qids)}")
    logger.info(f"  Model: {PRIMARY_MODEL} via {settings.CHAT_API_BASE}")
    logger.info(f"  Pacing: {pacing_delay:.1f}s | Checkpoint: {checkpoint_file}")
    logger.info("=" * 80)

    checkpoint_entries = list(existing_entries)

    for idx, qid in enumerate(remaining_qids, start=1):
        q_meta = queries[qid]
        query_text = q_meta["query"]
        category = q_meta["source"]
        ref_answer = answers[qid]
        qrel = qrels[qid]
        gold_doc = qrel["doc_id"]
        gold_sec = qrel["section_id"]

        logger.info(
            f"\n[{len(checkpoint_entries) + 1}/{len(target_qids)}] QID: {qid[:8]} | Category: {category} | Gold Doc: {gold_doc}"
        )
        logger.info(f"  Query: \"{query_text[:90]}{'...' if len(query_text) > 90 else ''}\"")

        max_retries = 3
        exec_res = None
        for attempt in range(max_retries):
            try:
                exec_res = await execute_query_single_attempt(
                    query_text=query_text,
                    target_model=PRIMARY_MODEL,
                )
                break
            except Exception as exc:
                logger.warning(f"  [QID {qid[:8]}] Attempt {attempt + 1}/{max_retries} failed: {exc}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5.0 * (attempt + 1))
                else:
                    raise

        cleaned_cit = clean_citations(exec_res["raw_citations"])
        visual_count = count_visual_evidence(cleaned_cit)

        entry: Dict[str, Any] = {
            "qid": qid,
            "category": category,
            "query": query_text,
            "reference_answer": ref_answer,
            "gold_doc_id": gold_doc,
            "gold_section_id": int(gold_sec),
            "generated_answer": exec_res["generated_answer"],
            "citations": cleaned_cit,
            "visual_evidence_count": visual_count,
            "timings": exec_res["timings"],
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_used": PRIMARY_MODEL,
        }

        validate_checkpoint_entry(entry)
        checkpoint_entries.append(entry)
        save_checkpoint_atomic(checkpoint_file, checkpoint_entries)

        t = entry["timings"]
        logger.info(
            f"  ✓ Success! Retrieval: {t['retrieval_ms']:.1f}ms | Generation: {t['generation_ms']:.1f}ms | Total: {t['total_ms']:.1f}ms"
        )
        logger.info(
            f"  Citations: {len(cleaned_cit)} | Answer Chars: {len(entry['generated_answer'])}"
        )

        del q_meta, query_text, ref_answer, qrel, exec_res, cleaned_cit, entry
        gc.collect()

        if idx < len(remaining_qids) and pacing_delay > 0:
            await asyncio.sleep(pacing_delay)

    logger.info("\n" + "=" * 80)
    logger.info(f"SPARK-X2.6 BENCHMARK RUN COMPLETE: {len(checkpoint_entries)}/{len(target_qids)} saved to {checkpoint_file}")
    logger.info("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Spark-X2.6 55-query evaluation")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries")
    parser.add_argument("--pacing", type=float, default=DEFAULT_PACING_DELAY, help="Pacing delay (sec)")
    parser.add_argument("--checkpoint", type=str, default=str(DEFAULT_CHECKPOINT_PATH), help="Checkpoint file path")
    parser.add_argument("--no-resume", action="store_true", help="Start from beginning")

    args = parser.parse_args()
    asyncio.run(
        run_benchmark(
            limit=args.limit,
            pacing_delay=args.pacing,
            checkpoint_file=Path(args.checkpoint),
            resume=not args.no_resume,
        )
    )
