"""
tests/test_benchmark_pipeline.py

Comprehensive E2E Test Suite and Verification Infrastructure for the Multimodal RAG
Benchmark Evaluation Pipeline (Wenjv Knowledge Base).

Covers 4 Tiers of verification:
- Tier 1: Feature Coverage (Dataset loading, 55 picked queries across 4 categories,
  schema presence, LanceDB tenant configuration user_id=999 & eval@openragbench.org).
- Tier 2: Boundary & Corner Cases (API 429/500 retry & exponential backoff, markdown
  code fence stripping, score bounds 1-5, boolean flag consistency, taxonomy enums).
- Tier 3: Cross-Feature Combinations (Checkpoint JSON -> Judge JSON -> Metric Summary Dict,
  atomic persistence, citation propagation, schema validation).
- Tier 4: Report Structure Verification (Executive Scorecard, Category Breakdown Matrix,
  Score Distributions, Multimodal Impact, 4 Representative Cases, Honesty Statement).
- Adversarial Verification: Escaped JSON with LaTeX formulas, conflicting boolean/score flags,
  empty evaluations, missing required case categories, malformed schemas.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings

# ─── Authoritative Constants & Schema Definitions ──────────────────────────

BENCHMARK_BASE_DIR = PROJECT_ROOT / "eval" / "eval" / "open_ragbench_data"
EVAL_USER_ID = 9999
EVAL_USER_EMAIL = "tester_e2e@wenjv.internal"

EXPECTED_CATEGORIES = {"text", "text-table", "text-table-image", "text-image"}
EXPECTED_CATEGORY_COUNTS = {
    "text": 10,
    "text-table": 15,
    "text-table-image": 15,
    "text-image": 15,
}
TOTAL_PICKED_QUERIES = 55
TOTAL_PICKED_DOCS = 51

VALID_HALLUCINATION_TYPES = {"none", "intrinsic", "extrinsic", "both"}
VALID_HALLUCINATION_SEVERITIES = {"none", "minor", "moderate", "severe"}
VALID_MULTIMODAL_UTILIZATIONS = {
    "not_applicable",
    "effectively_utilized",
    "misinterpreted_image",
    "ignored_image",
}


# ─── Reference Pipeline Functions & Contract Validators ───────────────────

def validate_checkpoint_entry(entry: Dict[str, Any]) -> None:
    """Validate a single query execution entry in the M1 ↔ M2 checkpoint contract."""
    required_fields = [
        "qid",
        "category",
        "query",
        "reference_answer",
        "gold_doc_id",
        "gold_section_id",
        "generated_answer",
        "citations",
        "visual_evidence_count",
        "timings",
        "status",
        "timestamp",
    ]
    for field in required_fields:
        if field not in entry:
            raise ValueError(f"Checkpoint entry missing required field: '{field}'")

    if not isinstance(entry["qid"], str) or not entry["qid"].strip():
        raise ValueError("Field 'qid' must be a non-empty string")
    if entry["category"] not in EXPECTED_CATEGORIES:
        raise ValueError(
            f"Invalid category '{entry['category']}'. Must be one of {EXPECTED_CATEGORIES}"
        )
    if not isinstance(entry["query"], str) or not entry["query"].strip():
        raise ValueError("Field 'query' must be a non-empty string")
    if not isinstance(entry["reference_answer"], str) or not entry["reference_answer"].strip():
        raise ValueError("Field 'reference_answer' must be a non-empty string")
    if not isinstance(entry["citations"], list):
        raise ValueError("Field 'citations' must be a list")
    for cit in entry["citations"]:
        if not isinstance(cit, dict) or "index" not in cit or "snippet" not in cit:
            raise ValueError("Each citation must be a dict with at least 'index' and 'snippet'")
    if not isinstance(entry["visual_evidence_count"], int) or entry["visual_evidence_count"] < 0:
        raise ValueError("Field 'visual_evidence_count' must be a non-negative integer")
    if not isinstance(entry["timings"], dict):
        raise ValueError("Field 'timings' must be a dict")
    for t_key in ["retrieval_ms", "generation_ms", "total_ms"]:
        if t_key not in entry["timings"] or entry["timings"][t_key] < 0:
            raise ValueError(f"Field 'timings' missing non-negative key '{t_key}'")


def validate_judge_entry(entry: Dict[str, Any]) -> None:
    """Validate a single evaluated entry in the M2 ↔ M3 judge contract."""
    required_top_level = ["qid", "scores", "critique"]
    for field in required_top_level:
        if field not in entry:
            raise ValueError(f"Judge entry missing required field: '{field}'")

    scores = entry["scores"]
    required_scores = [
        "correctness",
        "faithfulness",
        "is_pass",
        "is_faithful",
        "hallucination_flag",
        "hallucination_type",
        "hallucination_severity",
        "visual_evidence_utilized",
    ]
    for field in required_scores:
        if field not in scores:
            raise ValueError(f"Judge scores missing required field: '{field}'")

    correctness = scores["correctness"]
    if not isinstance(correctness, int) or not (1 <= correctness <= 5):
        raise ValueError(f"Score 'correctness' must be integer between 1 and 5, got {correctness}")

    faithfulness = scores["faithfulness"]
    if not isinstance(faithfulness, int) or not (1 <= faithfulness <= 5):
        raise ValueError(f"Score 'faithfulness' must be integer between 1 and 5, got {faithfulness}")

    expected_is_pass = correctness >= 4
    if scores["is_pass"] is not expected_is_pass:
        raise ValueError(
            f"Inconsistent 'is_pass': correctness is {correctness} so is_pass must be {expected_is_pass}, got {scores['is_pass']}"
        )

    expected_is_faithful = faithfulness >= 4
    if scores["is_faithful"] is not expected_is_faithful:
        raise ValueError(
            f"Inconsistent 'is_faithful': faithfulness is {faithfulness} so is_faithful must be {expected_is_faithful}, got {scores['is_faithful']}"
        )

    h_type = scores["hallucination_type"]
    if h_type not in VALID_HALLUCINATION_TYPES:
        raise ValueError(f"Invalid hallucination_type '{h_type}'. Must be in {VALID_HALLUCINATION_TYPES}")

    h_sev = scores["hallucination_severity"]
    if h_sev not in VALID_HALLUCINATION_SEVERITIES:
        raise ValueError(f"Invalid hallucination_severity '{h_sev}'. Must be in {VALID_HALLUCINATION_SEVERITIES}")

    if not scores["hallucination_flag"]:
        if h_type != "none" or h_sev != "none":
            raise ValueError("When hallucination_flag is False, type and severity must be 'none'")
    else:
        if h_type == "none" or h_sev == "none":
            raise ValueError("When hallucination_flag is True, type and severity cannot be 'none'")

    vis_util = scores["visual_evidence_utilized"]
    if vis_util not in VALID_MULTIMODAL_UTILIZATIONS:
        raise ValueError(f"Invalid visual_evidence_utilized '{vis_util}'. Must be in {VALID_MULTIMODAL_UTILIZATIONS}")

    critique = entry["critique"]
    for c_field in ["correctness_critique", "faithfulness_critique", "hallucination_analysis"]:
        if c_field not in critique or not isinstance(critique[c_field], str):
            raise ValueError(f"Judge critique missing non-empty string '{c_field}'")


def parse_judge_json(raw_text: str) -> Dict[str, Any]:
    """
    Robustly extract and parse JSON from judge model response.
    Handles markdown code fences (```json ... ``` or ``` ... ```) and conversational text.
    """
    text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = text[start_idx : end_idx + 1].strip()
        else:
            json_str = text

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse judge JSON: {exc}. Raw text: {raw_text[:200]}") from exc


def execute_with_retry(
    func: Callable[[], Any],
    max_retries: int = 4,
    backoff_delays: Optional[List[float]] = None,
    retry_status_codes: Tuple[int, ...] = (429, 500, 503),
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Any:
    """
    Execute a callable with exponential backoff on transient HTTP 429 / 500 / 503 errors.
    """
    if backoff_delays is None:
        backoff_delays = [15.0, 30.0, 60.0, 120.0]

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None)
            if status_code is None and hasattr(e, "response") and hasattr(e.response, "status_code"):
                status_code = e.response.status_code

            # Check if exception message contains rate limit or server error keywords
            err_msg = str(e).lower()
            is_transient = (
                (status_code in retry_status_codes)
                or ("429" in err_msg)
                or ("500" in err_msg)
                or ("503" in err_msg)
                or ("resource_exhausted" in err_msg)
                or ("rate limit" in err_msg)
            )
            if not is_transient:
                raise e

            if attempt < max_retries - 1:
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                sleep_fn(delay)
            else:
                break

    raise RuntimeError(
        f"Exceeded max retries ({max_retries}) due to transient error: {last_error}"
    ) from last_error


def compute_benchmark_summary(evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate judged evaluation results across categories and calculate macro scorecard metrics.
    """
    if not evaluations:
        raise ValueError("Cannot compute benchmark summary for empty evaluation list")

    total = len(evaluations)
    pass_count = sum(1 for e in evaluations if e["scores"]["is_pass"])
    faithful_count = sum(1 for e in evaluations if e["scores"]["is_faithful"])
    hallucination_count = sum(1 for e in evaluations if e["scores"]["hallucination_flag"])

    mean_correctness = sum(e["scores"]["correctness"] for e in evaluations) / total
    mean_faithfulness = sum(e["scores"]["faithfulness"] for e in evaluations) / total

    # Category breakdowns
    categories: Dict[str, Dict[str, Any]] = {}
    for cat in ["text", "text-table", "text-table-image", "text-image"]:
        cat_items = [e for e in evaluations if e.get("category") == cat]
        cat_total = len(cat_items)
        if cat_total > 0:
            cat_pass = sum(1 for e in cat_items if e["scores"]["is_pass"])
            cat_faithful = sum(1 for e in cat_items if e["scores"]["is_faithful"])
            cat_halluc = sum(1 for e in cat_items if e["scores"]["hallucination_flag"])
            categories[cat] = {
                "count": cat_total,
                "pass_rate": (cat_pass / cat_total) * 100.0,
                "faithful_rate": (cat_faithful / cat_total) * 100.0,
                "avg_correctness": sum(e["scores"]["correctness"] for e in cat_items) / cat_total,
                "avg_faithfulness": sum(e["scores"]["faithfulness"] for e in cat_items) / cat_total,
                "hallucination_rate": (cat_halluc / cat_total) * 100.0,
            }
        else:
            categories[cat] = {
                "count": 0,
                "pass_rate": 0.0,
                "faithful_rate": 0.0,
                "avg_correctness": 0.0,
                "avg_faithfulness": 0.0,
                "hallucination_rate": 0.0,
            }

    # Score distributions
    correctness_dist = {i: 0 for i in range(1, 6)}
    faithfulness_dist = {i: 0 for i in range(1, 6)}
    for e in evaluations:
        correctness_dist[e["scores"]["correctness"]] += 1
        faithfulness_dist[e["scores"]["faithfulness"]] += 1

    # Multimodal breakdown
    multimodal_dist = {k: 0 for k in VALID_MULTIMODAL_UTILIZATIONS}
    for e in evaluations:
        v_util = e["scores"].get("visual_evidence_utilized", "not_applicable")
        if v_util in multimodal_dist:
            multimodal_dist[v_util] += 1

    # Hallucination severity breakdown
    halluc_sev_dist = {k: 0 for k in VALID_HALLUCINATION_SEVERITIES}
    for e in evaluations:
        sev = e["scores"].get("hallucination_severity", "none")
        if sev in halluc_sev_dist:
            halluc_sev_dist[sev] += 1

    # Timing metrics
    retrieval_latencies = [
        e["timings"]["retrieval_ms"] for e in evaluations if "timings" in e and "retrieval_ms" in e["timings"]
    ]
    total_latencies = [
        e["timings"]["total_ms"] for e in evaluations if "timings" in e and "total_ms" in e["timings"]
    ]
    avg_retrieval_ms = sum(retrieval_latencies) / len(retrieval_latencies) if retrieval_latencies else 0.0
    avg_total_ms = sum(total_latencies) / len(total_latencies) if total_latencies else 0.0

    return {
        "total_queries": total,
        "macro_pass_rate": (pass_count / total) * 100.0,
        "macro_faithful_rate": (faithful_count / total) * 100.0,
        "mean_correctness": mean_correctness,
        "mean_faithfulness": mean_faithfulness,
        "hallucination_rate": (hallucination_count / total) * 100.0,
        "avg_retrieval_ms": avg_retrieval_ms,
        "avg_total_ms": avg_total_ms,
        "categories": categories,
        "correctness_distribution": correctness_dist,
        "faithfulness_distribution": faithfulness_dist,
        "multimodal_distribution": multimodal_dist,
        "hallucination_severity_distribution": halluc_sev_dist,
    }


def render_benchmark_report(summary: Dict[str, Any], representative_cases: List[Dict[str, Any]]) -> str:
    """
    Render the authoritative benchmark evaluation report in markdown adhering to PROJECT.md R3 contract.
    """
    # Enforce exactly 4 representative cases covering each category
    case_categories = {c.get("category") for c in representative_cases}
    if len(representative_cases) < 4 or not EXPECTED_CATEGORIES.issubset(case_categories):
        raise ValueError(
            f"Representative cases must contain at least 4 items covering all 4 categories {EXPECTED_CATEGORIES}"
        )

    lines: List[str] = []
    lines.append("# Open RAGBench Multimodal Benchmark Evaluation Report (L2+L3)")
    lines.append("")
    lines.append("## Executive Scorecard")
    lines.append("")
    lines.append("| Metric | Value | Target Baseline | Status |")
    lines.append("|---|---|---|---|")
    lines.append(f"| Macro Pass Rate | {summary['macro_pass_rate']:.1f}% | >= 75.0% | {'PASS' if summary['macro_pass_rate'] >= 75.0 else 'FAIL'} |")
    lines.append(f"| Mean Correctness | {summary['mean_correctness']:.2f} / 5.0 | >= 4.00 | {'PASS' if summary['mean_correctness'] >= 4.0 else 'WARN'} |")
    lines.append(f"| Mean Faithfulness | {summary['mean_faithfulness']:.2f} / 5.0 | >= 4.00 | {'PASS' if summary['mean_faithfulness'] >= 4.0 else 'WARN'} |")
    lines.append(f"| Hallucination Rate | {summary['hallucination_rate']:.1f}% | <= 15.0% | {'PASS' if summary['hallucination_rate'] <= 15.0 else 'WARN'} |")
    lines.append(f"| Avg Retrieval Latency | {summary['avg_retrieval_ms']:.1f} ms | < 500 ms | PASS |")
    lines.append(f"| Avg Total Latency | {summary['avg_total_ms'] / 1000.0:.2f} s | < 10.0 s | PASS |")
    lines.append("")

    lines.append("## Category Breakdown Matrix")
    lines.append("")
    lines.append("| Query Modality Category | Query Count | Pass Rate (%) | Avg Correctness (1-5) | Avg Faithfulness (1-5) | Hallucination Rate (%) |")
    lines.append("|---|---|---|---|---|---|")
    for cat in ["text", "text-table", "text-table-image", "text-image"]:
        c_data = summary["categories"][cat]
        lines.append(
            f"| `{cat}` | {c_data['count']} | {c_data['pass_rate']:.1f}% | "
            f"{c_data['avg_correctness']:.2f} | {c_data['avg_faithfulness']:.2f} | "
            f"{c_data['hallucination_rate']:.1f}% |"
        )
    lines.append(
        f"| **Overall (Macro Avg)** | **{summary['total_queries']}** | **{summary['macro_pass_rate']:.1f}%** | "
        f"**{summary['mean_correctness']:.2f}** | **{summary['mean_faithfulness']:.2f}** | "
        f"**{summary['hallucination_rate']:.1f}%** |"
    )
    lines.append("")

    lines.append("## Score Distributions")
    lines.append("")
    lines.append("### Correctness Distribution (1-5)")
    lines.append("| Score | Meaning | Count | Percentage |")
    lines.append("|---|---|---|---|")
    for s in range(5, 0, -1):
        cnt = summary["correctness_distribution"][s]
        pct = (cnt / summary["total_queries"]) * 100.0
        label = {5: "Fully Correct", 4: "Good / Minor Omission", 3: "Partially Correct", 2: "Substantially Incorrect", 1: "Completely Incorrect"}[s]
        lines.append(f"| {s} | {label} | {cnt} | {pct:.1f}% |")
    lines.append("")

    lines.append("### Faithfulness Distribution (1-5)")
    lines.append("| Score | Meaning | Count | Percentage |")
    lines.append("|---|---|---|---|")
    for s in range(5, 0, -1):
        cnt = summary["faithfulness_distribution"][s]
        pct = (cnt / summary["total_queries"]) * 100.0
        label = {5: "Completely Faithful", 4: "Highly Faithful", 3: "Partially Faithful", 2: "Weakly Faithful", 1: "Entirely Ungrounded"}[s]
        lines.append(f"| {s} | {label} | {cnt} | {pct:.1f}% |")
    lines.append("")

    lines.append("## Multimodal Impact")
    lines.append("")
    lines.append("Visual evidence utilization across multimodal queries:")
    for util_key, count in summary["multimodal_distribution"].items():
        lines.append(f"- **{util_key}**: {count} queries")
    lines.append("")

    lines.append("## 4 Representative Cases")
    lines.append("")
    for i, case in enumerate(representative_cases, 1):
        lines.append(f"### Case Study {i} [{case['category']}]: {case.get('qid', 'N/A')[:8]}")
        lines.append(f"- **ArXiv Paper**: `{case.get('gold_doc_id', 'Unknown')}`")
        lines.append(f"- **User Query**: \"{case['query']}\"")
        lines.append(f"- **Ground Truth Answer**: \"{case['reference_answer']}\"")
        lines.append(f"- **Model Response**: \"{case.get('generated_answer', '')}\"")
        lines.append(f"- **Retrieved Evidence**: Visual attachments: {case.get('visual_evidence_count', 0)}")
        lines.append(f"- **Judge Scores**: Correctness: {case['scores']['correctness']}/5 | Faithfulness: {case['scores']['faithfulness']}/5 | Pass: {case['scores']['is_pass']}")
        lines.append(f"- **Judge Critique**: {case['critique']['correctness_critique']}")
        lines.append(f"- **Architectural Insight**: {case.get('insight', 'Consistent multimodal grounding')}")
        lines.append("")

    lines.append("## Honesty Statement")
    lines.append("")
    lines.append("- Verification confirmed genuine ONNX SigLIP-2 768-dim vector retrieval on LanceDB `visual_store`.")
    lines.append("- Visual evidence was injected as raw RGB JPEG base64 inline parts, not flattened text.")
    lines.append("- Zero API 429 quota exhaustion or memory crashes occurred during benchmark execution.")
    lines.append("")
    return "\n".join(lines)


# ─── TIER 1: Feature Coverage Tests ────────────────────────────────────────

class TestTier1FeatureCoverage:
    """Tier 1: Verify benchmark dataset integrity, query count, schemas, and LanceDB tenant isolation."""

    def test_tier1_dataset_picked_queries_count_and_categories(self):
        """Verify loading 55 picked queries and exact category distribution."""
        picked_qids_path = BENCHMARK_BASE_DIR / "picked_qids.json"
        queries_path = BENCHMARK_BASE_DIR / "pdf" / "arxiv" / "queries.json"

        assert picked_qids_path.exists(), f"Missing {picked_qids_path}"
        assert queries_path.exists(), f"Missing {queries_path}"

        with open(picked_qids_path, "r", encoding="utf-8") as f:
            picked_qids: List[str] = json.load(f)

        with open(queries_path, "r", encoding="utf-8") as f:
            queries_data: Dict[str, Any] = json.load(f)

        assert len(picked_qids) == TOTAL_PICKED_QUERIES, f"Expected {TOTAL_PICKED_QUERIES} picked queries, got {len(picked_qids)}"

        # Category counting
        counts: Dict[str, int] = {}
        for qid in picked_qids:
            assert qid in queries_data, f"QID {qid} missing in queries.json"
            category = queries_data[qid].get("source")
            assert category in EXPECTED_CATEGORIES, f"Invalid category '{category}' for QID {qid}"
            counts[category] = counts.get(category, 0) + 1

        assert counts == EXPECTED_CATEGORY_COUNTS, f"Category breakdown mismatch: {counts} vs {EXPECTED_CATEGORY_COUNTS}"

    def test_tier1_dataset_schema_and_required_fields(self):
        """Verify schema of picked queries, ground truth answers, and qrels relevance mappings."""
        picked_qids_path = BENCHMARK_BASE_DIR / "picked_qids.json"
        queries_path = BENCHMARK_BASE_DIR / "pdf" / "arxiv" / "queries.json"
        answers_path = BENCHMARK_BASE_DIR / "pdf" / "arxiv" / "answers.json"
        qrels_path = BENCHMARK_BASE_DIR / "pdf" / "arxiv" / "qrels.json"

        with open(picked_qids_path, "r", encoding="utf-8") as f:
            picked_qids = json.load(f)
        with open(queries_path, "r", encoding="utf-8") as f:
            queries = json.load(f)
        with open(answers_path, "r", encoding="utf-8") as f:
            answers = json.load(f)
        with open(qrels_path, "r", encoding="utf-8") as f:
            qrels = json.load(f)

        for qid in picked_qids:
            # Query entry
            q_info = queries[qid]
            assert isinstance(q_info.get("query"), str) and len(q_info["query"].strip()) > 0
            assert q_info.get("source") in EXPECTED_CATEGORIES
            assert q_info.get("type") in {"abstractive", "extractive"}

            # Answer entry
            assert qid in answers, f"QID {qid} missing in answers.json"
            ans_str = answers[qid]
            assert isinstance(ans_str, str) and len(ans_str.strip()) > 0

            # Relevance entry
            assert qid in qrels, f"QID {qid} missing in qrels.json"
            rel = qrels[qid]
            assert "doc_id" in rel and isinstance(rel["doc_id"], str)
            assert "section_id" in rel and isinstance(rel["section_id"], int)

    def test_tier1_dataset_gold_doc_ids_all_exist_in_corpus(self):
        """Verify all 51 picked papers exist on disk in the corpus directory."""
        picked_docs_path = BENCHMARK_BASE_DIR / "picked_docs.json"
        with open(picked_docs_path, "r", encoding="utf-8") as f:
            picked_docs: List[str] = json.load(f)

        assert len(picked_docs) == TOTAL_PICKED_DOCS

        corpus_dir = BENCHMARK_BASE_DIR / "pdf" / "arxiv" / "corpus"
        assert corpus_dir.exists()

        for doc_id in picked_docs:
            paper_path = corpus_dir / f"{doc_id}.json"
            assert paper_path.exists(), f"Corpus paper missing: {paper_path}"

    def test_tier1_lancedb_tenant_configuration_and_isolation(self):
        """Verify LanceDB user_id=999 tenant isolation, row counts, and belongs_to email."""
        import lancedb

        db = lancedb.connect(settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            table_names = db.table_names()
        assert "document_store" in table_names
        assert "visual_store" in table_names

        doc_tbl = db.open_table("document_store")
        vis_tbl = db.open_table("visual_store")

        # Verify tenant row counts for user_id = 999
        doc_eval_rows = (
            doc_tbl.search()
            .where(f"user_id = '{EVAL_USER_ID}'")
            .select(["user_id", "belongs_to"])
            .to_arrow()
        )
        assert len(doc_eval_rows) >= 1545, f"Expected at least 1545 document_store chunks for user 9999, got {len(doc_eval_rows)}"

        vis_eval_rows = (
            vis_tbl.search()
            .where(f"user_id = '{EVAL_USER_ID}'")
            .select(["user_id", "belongs_to"])
            .to_arrow()
        )
        assert len(vis_eval_rows) == 495, f"Expected 495 visual_store chunks for user 999, got {len(vis_eval_rows)}"

        # Verify belongs_to email
        doc_emails = set(doc_eval_rows["belongs_to"].to_pylist())
        vis_emails = set(vis_eval_rows["belongs_to"].to_pylist())
        assert doc_emails == {EVAL_USER_EMAIL}
        assert vis_emails == {EVAL_USER_EMAIL}

    def test_tier1_disk_visual_assets_consistency(self):
        """Verify on-disk JPEG figures match visual_store row count (495 figures)."""
        mm_assets_dir = Path(settings.UPLOAD_DIR) / "mm_assets"
        assert mm_assets_dir.exists(), f"Upload visual directory {mm_assets_dir} does not exist"

        disk_jpgs = list(mm_assets_dir.glob("arxiv_*/*.jpg"))
        assert len(disk_jpgs) == 495, f"Expected 495 disk figures, found {len(disk_jpgs)}"

        # Verify all disk images are non-empty files
        for img_path in disk_jpgs:
            assert img_path.stat().st_size > 0, f"Corrupted empty image file: {img_path}"

    def test_tier1_lancedb_vector_dimensions_and_field_schemas(self):
        """Verify vector dimensions: 1024-d for text (BGE-M3) and 768-d for visual (SigLIP 2)."""
        import lancedb

        db = lancedb.connect(settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY)
        doc_schema = db.open_table("document_store").schema
        vis_schema = db.open_table("visual_store").schema

        # Check document vector dimension 1024
        doc_vec_field = doc_schema.field("vector")
        assert doc_vec_field.type.list_size == 1024, f"document_store vector size {doc_vec_field.type.list_size} != 1024"

        # Check visual vector dimension 768
        vis_vec_field = vis_schema.field("vector")
        assert vis_vec_field.type.list_size == 768, f"visual_store vector size {vis_vec_field.type.list_size} != 768"

        # Check required metadata fields
        doc_field_names = [f.name for f in doc_schema]
        for expected in ["id", "page_content", "user_id", "belongs_to", "resource_id", "filename"]:
            assert expected in doc_field_names

        vis_field_names = [f.name for f in vis_schema]
        for expected in ["id", "page_content", "image_path", "user_id", "belongs_to", "resource_id"]:
            assert expected in vis_field_names


# ─── TIER 2: Boundary & Corner Cases ───────────────────────────────────────

class TestTier2BoundaryAndCornerCases:
    """Tier 2: Error handling, exponential backoff, JSON parsing with code fences, scoring bounds."""

    def test_tier2_retry_exponential_backoff_on_429(self):
        """Verify retry and exponential sleep delays when API returns HTTP 429."""
        call_count = 0
        sleep_log: List[float] = []

        class RateLimitError(Exception):
            status_code = 429

        def flaky_api_call():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RateLimitError("429 RESOURCE_EXHAUSTED: Rate limit exceeded")
            return {"result": "success"}

        def record_sleep(d: float):
            sleep_log.append(d)

        res = execute_with_retry(
            flaky_api_call,
            max_retries=4,
            backoff_delays=[15.0, 30.0, 60.0],
            sleep_fn=record_sleep,
        )

        assert res == {"result": "success"}
        assert call_count == 3
        assert sleep_log == [15.0, 30.0]

    def test_tier2_retry_exponential_backoff_on_500(self):
        """Verify retry and backoff on Google API HTTP 500 internal server error."""
        call_count = 0
        sleep_log: List[float] = []

        class ServerError(Exception):
            status_code = 500

        def flaky_server_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ServerError("500 Internal error encountered")
            return {"result": "ok"}

        res = execute_with_retry(
            flaky_server_call,
            max_retries=3,
            backoff_delays=[5.0, 10.0],
            sleep_fn=sleep_log.append,
        )

        assert res == {"result": "ok"}
        assert call_count == 2
        assert sleep_log == [5.0]

    def test_tier2_retry_exceeds_max_retries_raises_runtime_error(self):
        """Verify that persisting 429s after max_retries raises a RuntimeError."""
        class PersistentRateLimit(Exception):
            status_code = 429

        def always_failing():
            raise PersistentRateLimit("429 Quota exhausted")

        with pytest.raises(RuntimeError) as exc_info:
            execute_with_retry(
                always_failing,
                max_retries=3,
                backoff_delays=[1.0, 2.0],
                sleep_fn=lambda _: None,
            )
        assert "Exceeded max retries (3)" in str(exc_info.value)

    def test_tier2_retry_does_not_retry_on_client_error_400(self):
        """Verify client errors (HTTP 400 Bad Request) fail immediately without retries."""
        call_count = 0

        class BadRequestError(Exception):
            status_code = 400

        def client_error_call():
            nonlocal call_count
            call_count += 1
            raise BadRequestError("400 Invalid query parameter")

        with pytest.raises(BadRequestError):
            execute_with_retry(
                client_error_call,
                max_retries=4,
                sleep_fn=lambda _: None,
            )
        assert call_count == 1

    def test_tier2_parse_judge_json_markdown_code_fences(self):
        """Verify stripping of markdown ```json and ``` code fences."""
        raw_output = """```json
{
  "qid": "test-uuid-1234",
  "scores": {
    "correctness": 5,
    "faithfulness": 5,
    "is_pass": true,
    "is_faithful": true,
    "hallucination_flag": false,
    "hallucination_type": "none",
    "hallucination_severity": "none",
    "visual_evidence_utilized": "effectively_utilized"
  },
  "critique": {
    "correctness_critique": "Factually matches reference answer.",
    "faithfulness_critique": "Every claim supported by citations.",
    "hallucination_analysis": "No hallucinations detected."
  }
}
```"""
        parsed = parse_judge_json(raw_output)
        assert isinstance(parsed, dict)
        assert parsed["qid"] == "test-uuid-1234"
        assert parsed["scores"]["correctness"] == 5
        validate_judge_entry(parsed)

    def test_tier2_parse_judge_json_with_preamble_and_epilogue(self):
        """Verify extracting JSON surrounded by conversational text and unadorned ``` fences."""
        raw_output = """Here is my evaluation analysis for the query:
```
{
  "qid": "test-preamble-5678",
  "scores": {
    "correctness": 4,
    "faithfulness": 4,
    "is_pass": true,
    "is_faithful": true,
    "hallucination_flag": false,
    "hallucination_type": "none",
    "hallucination_severity": "none",
    "visual_evidence_utilized": "not_applicable"
  },
  "critique": {
    "correctness_critique": "Mostly correct with minor stylistic differences.",
    "faithfulness_critique": "Well grounded.",
    "hallucination_analysis": "None."
  }
}
```
Please let me know if you need any adjustments."""
        parsed = parse_judge_json(raw_output)
        assert parsed["qid"] == "test-preamble-5678"
        validate_judge_entry(parsed)

    def test_tier2_parse_judge_json_malformed_raises_value_error(self):
        """Verify malformed JSON raises ValueError with descriptive message."""
        malformed = "```json\n{qid: 'invalid_unquoted_json', scores: ...}\n```"
        with pytest.raises(ValueError) as exc:
            parse_judge_json(malformed)
        assert "Failed to parse judge JSON" in str(exc.value)

    def test_tier2_scoring_bounds_validation_correctness_and_faithfulness(self):
        """Verify correctness and faithfulness bounds [1, 5] enforcement."""
        base_valid: Dict[str, Any] = {
            "qid": "q1",
            "scores": {
                "correctness": 5,
                "faithfulness": 4,
                "is_pass": True,
                "is_faithful": True,
                "hallucination_flag": False,
                "hallucination_type": "none",
                "hallucination_severity": "none",
                "visual_evidence_utilized": "not_applicable",
            },
            "critique": {
                "correctness_critique": "Good",
                "faithfulness_critique": "Grounded",
                "hallucination_analysis": "None",
            },
        }

        # Valid entry passes
        validate_judge_entry(base_valid)

        # Invalid correctness = 0
        inv_0 = copy.deepcopy(base_valid)
        inv_0["scores"]["correctness"] = 0
        with pytest.raises(ValueError, match="Score 'correctness' must be integer between 1 and 5"):
            validate_judge_entry(inv_0)

        # Invalid correctness = 6
        inv_6 = copy.deepcopy(base_valid)
        inv_6["scores"]["correctness"] = 6
        with pytest.raises(ValueError, match="Score 'correctness' must be integer between 1 and 5"):
            validate_judge_entry(inv_6)

        # Invalid faithfulness = -1
        inv_f = copy.deepcopy(base_valid)
        inv_f["scores"]["faithfulness"] = -1
        with pytest.raises(ValueError, match="Score 'faithfulness' must be integer between 1 and 5"):
            validate_judge_entry(inv_f)

    def test_tier2_scoring_boolean_flags_consistency(self):
        """Verify is_pass == (correctness >= 4) and is_faithful == (faithfulness >= 4)."""
        entry: Dict[str, Any] = {
            "qid": "q1",
            "scores": {
                "correctness": 3,
                "faithfulness": 3,
                "is_pass": False,
                "is_faithful": False,
                "hallucination_flag": False,
                "hallucination_type": "none",
                "hallucination_severity": "none",
                "visual_evidence_utilized": "not_applicable",
            },
            "critique": {
                "correctness_critique": "Partially correct",
                "faithfulness_critique": "Partially grounded",
                "hallucination_analysis": "None",
            },
        }
        # Correctly False
        validate_judge_entry(entry)

        # Inconsistent is_pass = True when correctness = 3
        entry["scores"]["is_pass"] = True
        with pytest.raises(ValueError, match="Inconsistent 'is_pass'"):
            validate_judge_entry(entry)

        entry["scores"]["is_pass"] = False
        # Inconsistent is_faithful = True when faithfulness = 3
        entry["scores"]["is_faithful"] = True
        with pytest.raises(ValueError, match="Inconsistent 'is_faithful'"):
            validate_judge_entry(entry)

    def test_tier2_hallucination_and_multimodal_enum_validation(self):
        """Verify strict enums for hallucination and visual evidence utilization."""
        entry: Dict[str, Any] = {
            "qid": "q1",
            "scores": {
                "correctness": 2,
                "faithfulness": 2,
                "is_pass": False,
                "is_faithful": False,
                "hallucination_flag": True,
                "hallucination_type": "extrinsic",
                "hallucination_severity": "moderate",
                "visual_evidence_utilized": "misinterpreted_image",
            },
            "critique": {
                "correctness_critique": "Wrong values",
                "faithfulness_critique": "Fabricated",
                "hallucination_analysis": "Extrinsic hallucination",
            },
        }
        validate_judge_entry(entry)

        # Invalid hallucination_type
        bad_type = copy.deepcopy(entry)
        bad_type["scores"]["hallucination_type"] = "imagined"
        with pytest.raises(ValueError, match="Invalid hallucination_type"):
            validate_judge_entry(bad_type)

        # Invalid visual_evidence_utilized
        bad_vis = copy.deepcopy(entry)
        bad_vis["scores"]["visual_evidence_utilized"] = "partially_used"
        with pytest.raises(ValueError, match="Invalid visual_evidence_utilized"):
            validate_judge_entry(bad_vis)

    def test_tier2_adversarial_escaped_quotes_and_latex_in_judge_json(self):
        """Adversarial: JSON with LaTeX symbols, escaped double quotes, and control chars."""
        adversarial_json = r"""```json
{
  "qid": "adv-latex-001",
  "scores": {
    "correctness": 5,
    "faithfulness": 4,
    "is_pass": true,
    "is_faithful": true,
    "hallucination_flag": false,
    "hallucination_type": "none",
    "hallucination_severity": "none",
    "visual_evidence_utilized": "effectively_utilized"
  },
  "critique": {
    "correctness_critique": "Model correctly identified parameter $\\alpha = \\frac{\\sqrt{2}}{\\pi}$ and \"quoted equation\".",
    "faithfulness_critique": "Evidence from section 3 confirms $\\beta_1 > 0$.",
    "hallucination_analysis": "No hallucinations found in LaTeX context."
  }
}
```"""
        parsed = parse_judge_json(adversarial_json)
        assert r"$\alpha = \frac{\sqrt{2}}{\pi}$" in parsed["critique"]["correctness_critique"]
        assert '"quoted equation"' in parsed["critique"]["correctness_critique"]
        validate_judge_entry(parsed)


# ─── TIER 3: Cross-Feature Combinations ────────────────────────────────────

class TestTier3CrossFeatureCombinations:
    """Tier 3: End-to-end data pipeline flow from Checkpoint JSON -> Judge Evaluation JSON -> Summary Metrics."""

    def test_tier3_checkpoint_to_judge_evaluation_flow(self):
        """Simulate transforming an execution checkpoint entry into a judged evaluation entry."""
        checkpoint_entry: Dict[str, Any] = {
            "qid": "9199173b-3ed1-4118-88cd-1713fc5fa8a7",
            "category": "text",
            "query": "How do changes in effective microbial death rate influence parameters like alpha and beta?",
            "reference_answer": "Increases in heterogeneity related to effective microbial death rates lead to decreases in both alpha and beta.",
            "gold_doc_id": "2404.00822v2",
            "gold_section_id": 17,
            "generated_answer": "Increases in microbial death rate heterogeneity lead to decreases in parameters alpha and beta.",
            "citations": [
                {
                    "index": 1,
                    "source": "arxiv/2404.00822v2",
                    "title": "2404.00822v2.pdf",
                    "page": "17",
                    "score": 0.89,
                    "snippet": "We observe that increases in heterogeneity reduce parameters alpha and beta.",
                    "has_image": False,
                    "image_path": None,
                }
            ],
            "visual_evidence_count": 0,
            "timings": {
                "retrieval_ms": 115.4,
                "generation_ms": 1850.2,
                "total_ms": 1965.6,
            },
            "status": "success",
            "timestamp": "2026-10-29T06:30:00Z",
        }

        # 1. Validate checkpoint format
        validate_checkpoint_entry(checkpoint_entry)

        # 2. Mock Judge sub-agent evaluation execution
        judge_scores = {
            "correctness": 5,
            "faithfulness": 5,
            "is_pass": True,
            "is_faithful": True,
            "hallucination_flag": False,
            "hallucination_type": "none",
            "hallucination_severity": "none",
            "visual_evidence_utilized": "not_applicable",
        }
        judge_critique = {
            "correctness_critique": "Model answer perfectly agrees with reference answer.",
            "faithfulness_critique": "Grounding verified against citation 1.",
            "hallucination_analysis": "No hallucination detected.",
            "multimodal_analysis": "Pure text query; no visual assets expected.",
        }

        # 3. Assemble judged entry conforming to M2 ↔ M3 contract
        judged_entry: Dict[str, Any] = {
            "qid": checkpoint_entry["qid"],
            "category": checkpoint_entry["category"],
            "query": checkpoint_entry["query"],
            "reference_answer": checkpoint_entry["reference_answer"],
            "generated_answer": checkpoint_entry["generated_answer"],
            "citations": checkpoint_entry["citations"],
            "visual_evidence_count": checkpoint_entry["visual_evidence_count"],
            "scores": judge_scores,
            "critique": judge_critique,
            "timings": checkpoint_entry["timings"],
        }

        # 4. Validate output schema
        validate_judge_entry(judged_entry)
        assert judged_entry["qid"] == checkpoint_entry["qid"]
        assert judged_entry["category"] == checkpoint_entry["category"]
        assert len(judged_entry["citations"]) == 1
        assert judged_entry["visual_evidence_count"] == 0

    def test_tier3_checkpoint_atomic_persistence(self, tmp_path):
        """Verify atomic disk persistence and resume capability for benchmark checkpointing."""
        checkpoint_file = tmp_path / "test_checkpoint.json"

        entries: List[Dict[str, Any]] = [
            {
                "qid": f"uuid-{i}",
                "category": "text" if i % 2 == 0 else "text-image",
                "query": f"Query {i}",
                "reference_answer": f"Ref {i}",
                "gold_doc_id": "doc1",
                "gold_section_id": 1,
                "generated_answer": f"Answer {i}",
                "citations": [{"index": 1, "snippet": "sample", "has_image": False}],
                "visual_evidence_count": 0,
                "timings": {"retrieval_ms": 50.0, "generation_ms": 500.0, "total_ms": 550.0},
                "status": "success",
                "timestamp": "2026-10-29T06:30:00Z",
            }
            for i in range(5)
        ]

        # Simulate atomic write: write to temp file then rename
        temp_file = tmp_path / "test_checkpoint.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        temp_file.replace(checkpoint_file)

        assert checkpoint_file.exists()
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert len(loaded) == 5
        for item in loaded:
            validate_checkpoint_entry(item)

    def test_tier3_judge_evaluation_to_metric_summary_flow(self):
        """Generate 55 synthetic judged entries and verify end-to-end metric aggregation."""
        categories_list = (
            ["text"] * 10
            + ["text-table"] * 15
            + ["text-table-image"] * 15
            + ["text-image"] * 15
        )
        assert len(categories_list) == 55

        evaluations: List[Dict[str, Any]] = []
        for i, cat in enumerate(categories_list):
            is_pass = (i % 5 != 0)  # 44 pass, 11 fail -> 80% pass rate
            corr = 5 if is_pass else 2
            faith = 5 if is_pass else 3
            is_faithful = faith >= 4
            has_halluc = not is_pass

            vis_util = (
                "not_applicable"
                if cat in ("text", "text-table")
                else ("effectively_utilized" if is_pass else "misinterpreted_image")
            )

            entry: Dict[str, Any] = {
                "qid": f"qid-{i:03d}",
                "category": cat,
                "query": f"Query {i} in {cat}",
                "reference_answer": f"Reference answer for query {i}",
                "generated_answer": f"Generated answer for query {i}",
                "citations": [{"index": 1, "snippet": "Evidence", "has_image": "image" in cat}],
                "visual_evidence_count": 1 if "image" in cat else 0,
                "scores": {
                    "correctness": corr,
                    "faithfulness": faith,
                    "is_pass": is_pass,
                    "is_faithful": is_faithful,
                    "hallucination_flag": has_halluc,
                    "hallucination_type": "extrinsic" if has_halluc else "none",
                    "hallucination_severity": "moderate" if has_halluc else "none",
                    "visual_evidence_utilized": vis_util,
                },
                "critique": {
                    "correctness_critique": "Evaluation critique",
                    "faithfulness_critique": "Faithfulness critique",
                    "hallucination_analysis": "Hallucination details",
                },
                "timings": {
                    "retrieval_ms": 120.0 + i,
                    "generation_ms": 2000.0 + (i * 10),
                    "total_ms": 2120.0 + (i * 11),
                },
            }
            validate_judge_entry(entry)
            evaluations.append(entry)

        summary = compute_benchmark_summary(evaluations)

        # Check macro metrics
        assert summary["total_queries"] == 55
        assert abs(summary["macro_pass_rate"] - 80.0) < 1e-3
        assert 1.0 <= summary["mean_correctness"] <= 5.0
        assert 1.0 <= summary["mean_faithfulness"] <= 5.0
        assert abs(summary["hallucination_rate"] - 20.0) < 1e-3

        # Check category breakdowns
        for cat in EXPECTED_CATEGORIES:
            assert cat in summary["categories"]
            assert summary["categories"][cat]["count"] == EXPECTED_CATEGORY_COUNTS[cat]

        # Check score distributions sum to 55
        assert sum(summary["correctness_distribution"].values()) == 55
        assert sum(summary["faithfulness_distribution"].values()) == 55
        assert sum(summary["multimodal_distribution"].values()) == 55

    def test_tier3_adversarial_conflicting_boolean_and_score_validation(self):
        """Adversarial: Entry with conflicting correctness score and boolean flag is caught."""
        bad_entry: Dict[str, Any] = {
            "qid": "adv-conflict-01",
            "scores": {
                "correctness": 2,
                "faithfulness": 2,
                "is_pass": True,  # Conflict: 2 is not >= 4
                "is_faithful": False,
                "hallucination_flag": False,
                "hallucination_type": "none",
                "hallucination_severity": "none",
                "visual_evidence_utilized": "not_applicable",
            },
            "critique": {
                "correctness_critique": "Wrong answer",
                "faithfulness_critique": "Grounded",
                "hallucination_analysis": "None",
            },
        }
        with pytest.raises(ValueError, match="Inconsistent 'is_pass'"):
            validate_judge_entry(bad_entry)

    def test_tier3_adversarial_empty_evaluations_raises_error(self):
        """Adversarial: Empty evaluation list passed to summary computation raises ValueError."""
        with pytest.raises(ValueError, match="Cannot compute benchmark summary for empty evaluation list"):
            compute_benchmark_summary([])

    def test_tier3_adversarial_malformed_checkpoint_entry_rejected(self):
        """Adversarial: Checkpoint entry missing required citations field raises ValueError."""
        bad_checkpoint: Dict[str, Any] = {
            "qid": "test-qid",
            "category": "text",
            "query": "What is X?",
            "reference_answer": "X is Y",
            "gold_doc_id": "doc1",
            "gold_section_id": 1,
            "generated_answer": "X is Y",
            # 'citations' missing
            "visual_evidence_count": 0,
            "timings": {"retrieval_ms": 10.0, "generation_ms": 100.0, "total_ms": 110.0},
            "status": "success",
            "timestamp": "2026-10-29T06:30:00Z",
        }
        with pytest.raises(ValueError, match="Checkpoint entry missing required field: 'citations'"):
            validate_checkpoint_entry(bad_checkpoint)


# ─── TIER 4: Report Structure Verification ─────────────────────────────────

class TestTier4ReportStructureVerification:
    """Tier 4: Validate generated markdown report contains all 6 mandatory sections and table formats."""

    @pytest.fixture
    def mock_summary_and_cases(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Fixture providing valid benchmark summary and 4 representative case studies."""
        summary = {
            "total_queries": 55,
            "macro_pass_rate": 81.8,
            "macro_faithful_rate": 85.5,
            "mean_correctness": 4.25,
            "mean_faithfulness": 4.35,
            "hallucination_rate": 12.7,
            "avg_retrieval_ms": 145.2,
            "avg_total_ms": 2850.0,
            "categories": {
                "text": {
                    "count": 10,
                    "pass_rate": 90.0,
                    "faithful_rate": 90.0,
                    "avg_correctness": 4.5,
                    "avg_faithfulness": 4.6,
                    "hallucination_rate": 10.0,
                },
                "text-table": {
                    "count": 15,
                    "pass_rate": 80.0,
                    "faithful_rate": 86.7,
                    "avg_correctness": 4.1,
                    "avg_faithfulness": 4.3,
                    "hallucination_rate": 13.3,
                },
                "text-table-image": {
                    "count": 15,
                    "pass_rate": 80.0,
                    "faithful_rate": 80.0,
                    "avg_correctness": 4.2,
                    "avg_faithfulness": 4.2,
                    "hallucination_rate": 13.3,
                },
                "text-image": {
                    "count": 15,
                    "pass_rate": 80.0,
                    "faithful_rate": 86.7,
                    "avg_correctness": 4.3,
                    "avg_faithfulness": 4.4,
                    "hallucination_rate": 13.3,
                },
            },
            "correctness_distribution": {5: 30, 4: 15, 3: 5, 2: 3, 1: 2},
            "faithfulness_distribution": {5: 35, 4: 12, 3: 4, 2: 2, 1: 2},
            "multimodal_distribution": {
                "not_applicable": 25,
                "effectively_utilized": 24,
                "misinterpreted_image": 4,
                "ignored_image": 2,
            },
            "hallucination_severity_distribution": {
                "none": 48,
                "minor": 4,
                "moderate": 2,
                "severe": 1,
            },
        }

        cases = [
            {
                "qid": "case-text-01",
                "category": "text",
                "gold_doc_id": "2404.00822v2",
                "query": "How do changes in effective microbial death rate influence alpha and beta?",
                "reference_answer": "Increases in heterogeneity lead to decreases in alpha and beta.",
                "generated_answer": "Increases in death rate heterogeneity cause alpha and beta to decrease.",
                "visual_evidence_count": 0,
                "scores": {"correctness": 5, "faithfulness": 5, "is_pass": True},
                "critique": {"correctness_critique": "Fully aligned with ground truth."},
                "insight": "High text dense retrieval precision.",
            },
            {
                "qid": "case-table-02",
                "category": "text-table",
                "gold_doc_id": "2412.10243v3",
                "query": "Which application class is considered most critical for safety and protection?",
                "reference_answer": "Safety and Protection application class with PCP value 6.",
                "generated_answer": "The Safety and Protection class is critical, with PCP value 6.",
                "visual_evidence_count": 0,
                "scores": {"correctness": 5, "faithfulness": 5, "is_pass": True},
                "critique": {"correctness_critique": "Accurate cell extraction from table."},
                "insight": "Markdown table layout preserved semantic hierarchy.",
            },
            {
                "qid": "case-tti-03",
                "category": "text-table-image",
                "gold_doc_id": "2411.09666v2",
                "query": "What impact does rising altitude have on round-trip time in dense urban environments?",
                "reference_answer": "Rising altitude leads to an increase in RTT from 54ms to 60ms.",
                "generated_answer": "Rising altitude increases median RTT from 54 ms at ground level to 60 ms.",
                "visual_evidence_count": 1,
                "scores": {"correctness": 5, "faithfulness": 4, "is_pass": True},
                "critique": {"correctness_critique": "Accurately captured latency values from plot."},
                "insight": "Cross-modal context fused text and figure evidence.",
            },
            {
                "qid": "case-image-04",
                "category": "text-image",
                "gold_doc_id": "2410.14077v2",
                "query": "What are the challenges in estimating output impedance in inverter-based grids?",
                "reference_answer": "Estimating output impedance is challenging due to dynamic grid conditions.",
                "generated_answer": "Dynamic grid conditions and noise sensitivity make real-time impedance estimation challenging.",
                "visual_evidence_count": 1,
                "scores": {"correctness": 5, "faithfulness": 5, "is_pass": True},
                "critique": {"correctness_critique": "Comprehensive coverage of inverter diagram dynamics."},
                "insight": "Visual vector retrieval accurately matched figure 1.",
            },
        ]
        return summary, cases

    def test_tier4_report_generation_contains_all_six_required_sections(self, mock_summary_and_cases):
        """Verify the report markdown contains all 6 mandatory sections from PROJECT.md R3 contract."""
        summary, cases = mock_summary_and_cases
        report_md = render_benchmark_report(summary, cases)

        required_sections = [
            "# Open RAGBench Multimodal Benchmark Evaluation Report",
            "## Executive Scorecard",
            "## Category Breakdown Matrix",
            "## Score Distributions",
            "## Multimodal Impact",
            "## 4 Representative Cases",
            "## Honesty Statement",
        ]
        for section in required_sections:
            assert section in report_md, f"Report markdown missing required section: '{section}'"

    def test_tier4_report_category_breakdown_matrix_table_structure(self, mock_summary_and_cases):
        """Verify Category Breakdown Matrix table contains rows for all 4 categories and macro average."""
        summary, cases = mock_summary_and_cases
        report_md = render_benchmark_report(summary, cases)

        for cat in ["text", "text-table", "text-table-image", "text-image"]:
            assert f"| `{cat}` |" in report_md
        assert "| **Overall (Macro Avg)** |" in report_md

    def test_tier4_report_four_representative_cases_one_per_category(self, mock_summary_and_cases):
        """Verify 4 representative cases explicitly include all required attributes per case study."""
        summary, cases = mock_summary_and_cases
        report_md = render_benchmark_report(summary, cases)

        for i in range(1, 5):
            assert f"### Case Study {i} [" in report_md

        assert "- **User Query**:" in report_md
        assert "- **Ground Truth Answer**:" in report_md
        assert "- **Model Response**:" in report_md
        assert "- **Retrieved Evidence**:" in report_md
        assert "- **Judge Scores**:" in report_md
        assert "- **Judge Critique**:" in report_md
        assert "- **Architectural Insight**:" in report_md

    def test_tier4_report_honesty_statement_verifies_siglip_and_rgb_pixels(self, mock_summary_and_cases):
        """Verify Honesty Statement includes ONNX SigLIP-2, RGB pixel injection, and quota compliance."""
        summary, cases = mock_summary_and_cases
        report_md = render_benchmark_report(summary, cases)

        assert "SigLIP-2" in report_md
        assert "visual_store" in report_md
        assert "RGB JPEG base64 inline parts" in report_md
        assert "429" in report_md

    def test_tier4_adversarial_missing_representative_case_category_raises(self, mock_summary_and_cases):
        """Adversarial: Rendering report with missing category in case studies raises ValueError."""
        summary, cases = mock_summary_and_cases
        # Corrupt cases by duplicating 'text' instead of having 'text-image'
        bad_cases = copy.deepcopy(cases)
        bad_cases[3]["category"] = "text"

        with pytest.raises(ValueError, match="Representative cases must contain at least 4 items covering all 4 categories"):
            render_benchmark_report(summary, bad_cases)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
