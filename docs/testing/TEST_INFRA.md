# TEST_INFRA: Multimodal RAG Benchmark Evaluation Test Infrastructure

## 1. Overview & Test Infrastructure Architecture

This document describes the test architecture, execution environment, and verification contracts implemented for the **Wenjv Multimodal RAG Benchmark & LLM Judge Evaluation Pipeline** (evaluating Gemma 4 31B IT on 55 picked ArXiv queries across 51 papers).

- **Test Suite Location**: `tests/test_benchmark_pipeline.py`
- **Primary Test Runner**: `/home/lanzao/antigravity/dazzling-bell/.venv/bin/pytest`
- **Python Runtime**: Python 3.14.8, Pytest 9.1.1, LanceDB, PyArrow, ONNXRuntime
- **Corpus & Benchmark Data Directory**: `eval/eval/open_ragbench_data/`
- **LanceDB Vector Storage**: `/home/lanzao/.config/wenjv/lance_db`
- **Visual Assets Directory**: `/home/lanzao/.config/wenjv/uploads/mm_assets/`

---

## 2. Four-Tier Test Verification Matrix

The test suite is structured into 4 comprehensive tiers plus adversarial edge cases:

| Tier | Focus Area | Test Count | Key Invariants Verified |
|---|---|:---:|---|
| **Tier 1** | **Feature Coverage** | 6 | - Exact 55 picked queries loaded across 4 categories: `text` (10), `text-table` (15), `text-table-image` (15), `text-image` (15).<br>- Schema presence: `qid`, `query`, `reference_answer`, `category`, `gold_doc_id`, `gold_section_id`.<br>- All 51 picked papers verified to exist in `corpus/`.<br>- LanceDB tenant isolation: exactly 1,545 text chunks in `document_store` and 495 visual chunks in `visual_store` belong to `user_id = '999'` and `belongs_to = 'eval@openragbench.org'`.<br>- Vector dimensions: 1024-d (BGE-M3) and 768-d (SigLIP-2).<br>- Disk visual assets: exactly 495 non-empty `.jpg` files match table count. |
| **Tier 2** | **Boundary & Corner Cases** | 11 | - Transient Google API HTTP 429 (Resource Exhausted) exponential backoff (15s -> 30s -> 60s) and recovery.<br>- Transient HTTP 500 (Internal Error) exponential backoff and recovery.<br>- Persistent failure raises `RuntimeError` after exhausting max retries.<br>- Client errors (HTTP 400) fail fast without retrying.<br>- Parsing judge output wrapped in markdown code fences (` ```json ` or unadorned ` ``` `).<br>- Parsing judge output embedded within conversational preamble/epilogue.<br>- Malformed JSON rejection with informative `ValueError`.<br>- Scoring boundaries: Correctness and Faithfulness strictly clamped to integer range [1, 5].<br>- Boolean flag consistency: `is_pass == (correctness >= 4)` and `is_faithful == (faithfulness >= 4)`.<br>- Taxonomy enums: `hallucination_type`, `hallucination_severity`, and `visual_evidence_utilized`.<br>- Adversarial: Escaped quotes, control characters, and LaTeX formulas (`$\alpha = \frac{\sqrt{2}}{\pi}$`) in judge JSON. |
| **Tier 3** | **Cross-Feature Combinations** | 6 | - End-to-end data transformation flow: Checkpoint Entry (M1) -> Judge Evaluation Entry (M2) -> Metric Summary Dict (M3).<br>- Citation preservation and visual evidence count propagation.<br>- Atomic checkpoint persistence (write-to-temp and rename) and resume capability.<br>- Aggregation across all 55 queries into Macro Pass Rate, Mean Correctness, Mean Faithfulness, and Hallucination Rate.<br>- Adversarial: Rejection of conflicting boolean flags and numerical scores.<br>- Adversarial: Empty evaluation list rejection preventing ZeroDivisionError.<br>- Adversarial: Malformed checkpoint entry missing citations rejected. |
| **Tier 4** | **Report Structure Verification** | 5 | - Verification that generated report contains all 6 required sections:<br>  1. `# Open RAGBench Multimodal Benchmark Evaluation Report`<br>  2. `## Executive Scorecard`<br>  3. `## Category Breakdown Matrix`<br>  4. `## Score Distributions`<br>  5. `## Multimodal Impact`<br>  6. `## 4 Representative Cases`<br>  7. `## Honesty Statement`<br>- Category Breakdown Matrix verifies rows for all 4 categories and Overall Macro Avg.<br>- Exactly 4 Representative Cases covering each modality with required fields (Query, Reference Answer, Model Response, Retrieved Evidence, Scores, Critique, Insight).<br>- Honesty statement confirms ONNX SigLIP-2 vector retrieval, raw RGB JPEG inline injection, and quota compliance.<br>- Adversarial: Enforces presence of all 4 query categories in case studies. |

**Total Test Suite Size**: **28 tests**, 100% passing.

---

## 3. How to Run the Tests

Execute pytest using the project virtual environment binary:

```bash
# Standard test run
/home/lanzao/antigravity/dazzling-bell/.venv/bin/pytest tests/test_benchmark_pipeline.py -v

# Run with explicit PYTHONPATH
PYTHONPATH=. /home/lanzao/antigravity/dazzling-bell/.venv/bin/pytest tests/test_benchmark_pipeline.py -v

# Run a specific tier (e.g. Tier 1)
/home/lanzao/antigravity/dazzling-bell/.venv/bin/pytest tests/test_benchmark_pipeline.py -k "TestTier1" -v
```

---

## 4. Downstream Milestone Interface Contracts

Downstream implementing agents (Milestones M1, M2, M3) must adhere to the interface contracts tested here:

### 4.1 Milestone M1 Contract: `eval/results/gemma_e2e_benchmark_checkpoint.json`
Each entry must contain:
- `qid`: string (UUID)
- `category`: `"text" | "text-table" | "text-table-image" | "text-image"`
- `query`: string
- `reference_answer`: string
- `gold_doc_id`: string
- `gold_section_id`: integer
- `generated_answer`: string
- `citations`: list of dicts with `index`, `snippet`, `has_image`, `image_path`
- `visual_evidence_count`: integer (>= 0)
- `timings`: dict with `retrieval_ms`, `generation_ms`, `total_ms`
- `status`: `"success" | "error"`
- `timestamp`: ISO8601 string

### 4.2 Milestone M2 Contract: `eval/results/gemma_e2e_judged_evaluations.json`
Each entry must contain:
- `qid`, `category`, `query`, `reference_answer`, `generated_answer`, `citations`, `visual_evidence_count`
- `scores`:
  - `correctness`: integer (1-5)
  - `faithfulness`: integer (1-5)
  - `is_pass`: boolean (`correctness >= 4`)
  - `is_faithful`: boolean (`faithfulness >= 4`)
  - `hallucination_flag`: boolean
  - `hallucination_type`: `"none" | "intrinsic" | "extrinsic" | "both"`
  - `hallucination_severity`: `"none" | "minor" | "moderate" | "severe"`
  - `visual_evidence_utilized`: `"not_applicable" | "effectively_utilized" | "misinterpreted_image" | "ignored_image"`
- `critique`:
  - `correctness_critique`: string
  - `faithfulness_critique`: string
  - `hallucination_analysis`: string
- `timings`: dict

### 4.3 Milestone M3 Contract: `eval/results/benchmark_report.md`
Must generate markdown containing the 6 mandatory sections, the Category Breakdown Matrix table, Correctness and Faithfulness frequency tables, 4 representative cases (one per category), and the RAG Honesty statement.
