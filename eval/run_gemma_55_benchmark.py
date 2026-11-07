"""
eval/run_gemma_55_benchmark.py

Milestone 1: 55-Query Multimodal RAG Benchmark Execution Runner.
Iterates through all 55 picked ArXiv queries, executes end-to-end multi-leg
retrieval and Gemma-4-31B chat generation (with Gemini-3.5-Flash resilience fallback),
and writes atomic checkpoints matching the M1 Checkpoint Contract.
"""
from __future__ import annotations

# ─── STEP 1: WSL2 IPv4 Socket Pinning ─────────────────────────────────────────
# Must be executed before any network libraries (httpx, anyio) or backend imports
import socket

_orig_getaddrinfo = socket.getaddrinfo


def enable_ipv4_socket_pinning() -> None:
    """
    Force socket.getaddrinfo to resolve only IPv4 (AF_INET) addresses.
    Prevents WSL2 dual-stack IPv6 unreachable routing hangs to Google APIs.
    """
    if getattr(socket, "_is_ipv4_pinned", False):
        return

    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_getaddrinfo
    socket._is_ipv4_pinned = True


enable_ipv4_socket_pinning()

# ─── STANDARD & THIRD-PARTY IMPORTS ─────────────────────────────────────────
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

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings
from backend.api.services.chat import rag_chat_events
from tests.test_benchmark_pipeline import validate_checkpoint_entry, EXPECTED_CATEGORIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gemma_55_benchmark")

# ─── PATHS & CONSTANTS ───────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "eval" / "eval" / "open_ragbench_data"
DEFAULT_CHECKPOINT_PATH = PROJECT_ROOT / "eval" / "results" / "gemma_e2e_benchmark_checkpoint.json"

EVAL_USER_ID = 999
EVAL_USER_EMAIL = "eval@openragbench.org"
EVAL_WINDOW_SIZE = 5

PRIMARY_MODEL = "gemma-4-31b-it"
FALLBACK_MODEL = "gemini-3.5-flash"
DEFAULT_BACKOFF_DELAYS = [15.0, 30.0, 60.0]
DEFAULT_PACING_DELAY = 5.0


def is_transient_error(exc: Exception) -> bool:
    """Determine whether an error is transient and retriable."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    err_str = str(exc).lower()
    return (
        "429" in err_str
        or "resource_exhausted" in err_str
        or "rate limit" in err_str
        or "500" in err_str
        or "502" in err_str
        or "503" in err_str
        or "504" in err_str
        or "internal error" in err_str
        or "timeout" in err_str
        or "timed out" in err_str
        or "connection" in err_str
        or "readtimeout" in err_str
        or "connecttimeout" in err_str
        or "siliconflow" in err_str
        or "402" in err_str
        or "payment required" in err_str
        or "google api unavailable" in err_str
        or "unavailable" in err_str
    )


def load_benchmark_dataset(base_dir: Path) -> Tuple[List[str], Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    """Load and validate all 55 picked queries and metadata from open_ragbench_data."""
    picked_qids_path = base_dir / "picked_qids.json"
    queries_path = base_dir / "pdf" / "arxiv" / "queries.json"
    answers_path = base_dir / "pdf" / "arxiv" / "answers.json"
    qrels_path = base_dir / "pdf" / "arxiv" / "qrels.json"

    for p in [picked_qids_path, queries_path, answers_path, qrels_path]:
        if not p.exists():
            raise FileNotFoundError(f"Required benchmark dataset file missing: {p}")

    with open(picked_qids_path, "r", encoding="utf-8") as f:
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
    """Load and validate existing checkpoint entries if present, enabling resumption."""
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
    """Atomically save checkpoint list to disk using temporary file rename."""
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = checkpoint_path.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, checkpoint_path)


def clean_citations(raw_citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format and normalize citation dicts matching M1 contract."""
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
    """Count visual evidence attachments (max 3 images resolved by VisualAssetStore)."""
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
    dry_run: bool = False,
    timeout_sec: float = 90.0,
) -> Dict[str, Any]:
    """Execute a single rag_chat_events call targeting the specified model."""
    # Override settings.CHAT_MODEL dynamically to guarantee correct routing in backend
    settings.CHAT_MODEL = target_model

    tokens: List[str] = []
    raw_citations: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    t_start = time.perf_counter()
    t_citations: Optional[float] = None

    if dry_run:
        from unittest.mock import patch

        async def _mock_stream(*args, **kwargs):
            yield f"Dry-run mock response generated for benchmark query testing: {query_text[:50]}"

        patcher = patch("backend.api.services.chat.stream_google_chat", side_effect=_mock_stream)
        patcher.start()

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

    try:
        if dry_run:
            await _consume()
        else:
            await asyncio.wait_for(_consume(), timeout=timeout_sec)
    finally:
        if dry_run:
            patcher.stop()

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


async def execute_query_with_resilience(
    *,
    qid: str,
    query_text: str,
    max_retries: int = 3,
    backoff_delays: Optional[List[float]] = None,
    dry_run: bool = False,
) -> Tuple[Dict[str, Any], str]:
    """
    Execute query with two-tier resilience:
    Tier 1: Try PRIMARY_MODEL (gemma-4-31b-it) with exponential backoff on 429/500/timeout.
    Tier 2: If primary fails all retries, fall back to FALLBACK_MODEL (gemini-3.5-flash).
    """
    if backoff_delays is None:
        backoff_delays = DEFAULT_BACKOFF_DELAYS

    last_error: Optional[Exception] = None

    # Tier 1: Try Primary Model (Gemma)
    for attempt in range(max_retries):
        try:
            logger.info(f"  [QID {qid[:8]}] Attempting primary model '{PRIMARY_MODEL}' (try {attempt + 1}/{max_retries})...")
            result = await execute_query_single_attempt(
                query_text=query_text,
                target_model=PRIMARY_MODEL,
                dry_run=dry_run,
            )
            return result, PRIMARY_MODEL
        except Exception as exc:
            last_error = exc
            if not is_transient_error(exc) and attempt == 0:
                logger.error(f"  [QID {qid[:8]}] Non-transient error on primary model: {exc}")
                break

            if attempt < max_retries - 1:
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                logger.warning(
                    f"  [QID {qid[:8]}] Transient error ({exc}) on '{PRIMARY_MODEL}'. Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    f"  [QID {qid[:8]}] Primary model '{PRIMARY_MODEL}' exhausted {max_retries} attempts: {last_error}"
                )

    # Tier 2: Fallback to Gemini 3.5 Flash to guarantee 100% completion
    logger.warning(
        f"  [QID {qid[:8]}] Activating fallback model '{FALLBACK_MODEL}' to ensure reliable completion..."
    )

    for attempt in range(max_retries):
        try:
            logger.info(f"  [QID {qid[:8]}] Attempting fallback model '{FALLBACK_MODEL}' (try {attempt + 1}/{max_retries})...")
            result = await execute_query_single_attempt(
                query_text=query_text,
                target_model=FALLBACK_MODEL,
                dry_run=dry_run,
            )
            return result, FALLBACK_MODEL
        except Exception as exc:
            last_error = exc
            if not is_transient_error(exc) and attempt == 0:
                logger.error(f"  [QID {qid[:8]}] Non-transient error on fallback model: {exc}")
                raise exc

            if attempt < max_retries - 1:
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                logger.warning(f"  [QID {qid[:8]}] Transient error ({exc}) on fallback model. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                break

    raise RuntimeError(f"All retries and fallbacks failed for QID {qid}: {last_error}") from last_error


async def run_gemma_benchmark(
    *,
    limit: Optional[int] = None,
    pacing_delay: float = DEFAULT_PACING_DELAY,
    checkpoint_file: Path = DEFAULT_CHECKPOINT_PATH,
    resume: bool = True,
    dry_run: bool = False,
) -> None:
    """Main batch evaluation orchestrator."""
    # Ensure live un-cached RAG retrieval
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
    logger.info(f"Benchmark Configuration:")
    logger.info(f"  Target Queries: {len(target_qids)} | Already Completed: {len(completed_qids)} | Remaining: {len(remaining_qids)}")
    logger.info(f"  Execution Mode: {'DRY RUN (Mock LLM)' if dry_run else 'LIVE RAG + GEMMA 4 31B'}")
    logger.info(f"  Pacing Delay: {pacing_delay:.1f}s | Checkpoint Destination: {checkpoint_file}")
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

        exec_res, model_used = await execute_query_with_resilience(
            qid=qid,
            query_text=query_text,
            dry_run=dry_run,
        )

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
            "model_used": model_used,
        }

        # Contract assertion
        validate_checkpoint_entry(entry)

        checkpoint_entries.append(entry)
        save_checkpoint_atomic(checkpoint_file, checkpoint_entries)

        t = entry["timings"]
        logger.info(
            f"  ✓ Success ({model_used})! Retrieval: {t['retrieval_ms']:.1f}ms | Generation: {t['generation_ms']:.1f}ms | Total: {t['total_ms']:.1f}ms"
        )
        logger.info(
            f"  Visual Evidence Count: {visual_count} | Citations: {len(cleaned_cit)} | Answer Length: {len(entry['generated_answer'])} chars"
        )

        # Memory hygiene
        del q_meta, query_text, ref_answer, qrel, exec_res, cleaned_cit, entry
        gc.collect()

        # Quota pacing delay
        if idx < len(remaining_qids) and pacing_delay > 0:
            logger.info(f"  Pacing delay: sleeping {pacing_delay:.1f}s...")
            await asyncio.sleep(pacing_delay)

    logger.info("\n" + "=" * 80)
    logger.info(f"BENCHMARK COMPLETE: {len(checkpoint_entries)}/{len(target_qids)} queries saved to {checkpoint_file}")
    logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Milestone 1: 55-Query Gemma Benchmark Runner")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries to execute")
    parser.add_argument("--pacing-delay", type=float, default=DEFAULT_PACING_DELAY, help="Pacing delay between queries in seconds (default: 5.0)")
    parser.add_argument("--checkpoint-file", type=Path, default=DEFAULT_CHECKPOINT_PATH, help="Checkpoint file path")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume from existing checkpoint")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from existing checkpoint (default: True)")
    parser.add_argument("--dry-run", action="store_true", help="Run with mocked LLM generation to verify data flow without consuming API quota")
    args = parser.parse_args()

    asyncio.run(
        run_gemma_benchmark(
            limit=args.limit,
            pacing_delay=args.pacing_delay,
            checkpoint_file=args.checkpoint_file,
            resume=not args.no_resume,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
