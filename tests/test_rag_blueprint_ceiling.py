import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from backend.config import settings
from backend.api.services.search import truncate_by_score_gap, search_documents
from backend.core.utils import generate_deterministic_chunk_id, load_and_chunk_document
from langchain.schema import Document
import tempfile
import os


def test_truncate_by_score_gap_cliff():
    """Verify that a steep relative score drop truncates long-tail noise."""
    candidates = [
        ("doc_1", 0.95),
        ("doc_2", 0.88),
        ("doc_3", 0.82),
        ("doc_4", 0.25),  # (0.82 - 0.25) / 0.82 = 0.695 (> 0.40 threshold)
        ("doc_5", 0.10),
    ]
    res = truncate_by_score_gap(candidates, min_keep=2, max_keep=8, rel_gap_threshold=0.40)
    assert len(res) == 3
    assert [d[0] for d in res] == ["doc_1", "doc_2", "doc_3"]


def test_truncate_by_score_gap_gradual_slope():
    """Verify that gradual score declines preserve up to max_keep."""
    candidates = [
        ("doc_1", 0.90),
        ("doc_2", 0.85),
        ("doc_3", 0.80),
        ("doc_4", 0.75),
        ("doc_5", 0.70),
    ]
    res = truncate_by_score_gap(candidates, min_keep=2, max_keep=4, rel_gap_threshold=0.40)
    assert len(res) == 4
    assert [d[0] for d in res] == ["doc_1", "doc_2", "doc_3", "doc_4"]


def test_truncate_by_score_gap_min_keep_guard():
    """Verify that min_keep is honored even if a cliff occurs at index 1."""
    candidates = [
        ("doc_1", 0.95),
        ("doc_2", 0.30),
        ("doc_3", 0.10),
    ]
    res = truncate_by_score_gap(candidates, min_keep=2, max_keep=5, rel_gap_threshold=0.40)
    assert len(res) == 2
    assert [d[0] for d in res] == ["doc_1", "doc_2"]


def test_deterministic_chunk_id_stability():
    """Verify deterministic chunk ID produces stable hashes across invocations."""
    id1 = generate_deterministic_chunk_id("res_101", 0, "Hello world this is chunk content", "Docs > Arch")
    id2 = generate_deterministic_chunk_id("res_101", 0, "Hello world this is chunk content", "Docs > Arch")
    id3 = generate_deterministic_chunk_id("res_101", 1, "Hello world this is chunk content", "Docs > Arch")
    id4 = generate_deterministic_chunk_id("res_102", 0, "Hello world this is chunk content", "Docs > Arch")

    assert id1 == id2
    assert id1 != id3
    assert id1 != id4
    assert len(id1) == 24


def test_markdown_heading_breadcrumb_extraction_and_bi_text(monkeypatch):
    """Verify markdown headings inject breadcrumbs into indexing_text while keeping text clean."""
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", True)
    monkeypatch.setattr(settings, "CHUNK_RETRIEVAL_SIZE", 60)

    md_content = """# 架构总览
系统采用多层次向量与全文双引擎检索架构，旨在大幅提升大规模知识库的检索质量和召回率。

## 检索管道
两阶段混合检索结合了向量相似度与BM25关键词检索，有效平衡语义关联与专有名词精确匹配。

### 断层截断
通过动态计算分数一阶差分与相对跌幅，有效截断长尾噪声分块，显著降低LLM上下文污染与幻觉风险。
"""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md_content)
        temp_path = f.name

    try:
        chunks = load_and_chunk_document(temp_path, resource_id="res_999")
        assert len(chunks) >= 3

        # Verify breadcrumbs presence in indexing_text
        has_arch_crumb = any("[架构总览" in c.get("indexing_text", "") for c in chunks)
        has_pipeline_crumb = any("检索管道" in c.get("indexing_text", "") for c in chunks)
        assert has_arch_crumb
        assert has_pipeline_crumb

        # Verify assembly text remains pure clean text
        for c in chunks:
            assert not c["text"].startswith("[架构总览")

        # Verify neighbor pointers
        for i in range(len(chunks) - 1):
            assert chunks[i]["next_chunk_id"] == chunks[i + 1]["chunk_id"]
            assert chunks[i + 1]["prev_chunk_id"] == chunks[i]["chunk_id"]

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
async def test_search_rerank_with_cliff_truncation(monkeypatch):
    """Verify that search_documents applies cliff truncation after reranking."""
    monkeypatch.setattr(settings, "HYBRID_SEARCH_ENABLED", False)
    monkeypatch.setattr(settings, "MMR_ENABLED", False)
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "RERANK_CANDIDATES", 10)
    monkeypatch.setattr(settings, "RERANK_MIN_KEEP", 2)
    monkeypatch.setattr(settings, "RERANK_REL_GAP_THRESHOLD", 0.40)

    with patch('backend.api.services.search.vector_store') as m_store, \
         patch('backend.core.rerank_client.rerank', new_callable=AsyncMock) as m_rerank:

        # 5 candidates returned from vector store
        docs = [
            Document(page_content=f"content_{i}", metadata={"id": f"doc_{i}"})
            for i in range(5)
        ]
        m_store.fetch_documents.return_value = [(d, 0.1 * i) for i, d in enumerate(docs)]

        # Rerank gives 2 high scores, then a 60% cliff drop for doc 2, 3, 4
        m_rerank.return_value = [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.90},
            {"index": 2, "relevance_score": 0.30},  # drop > 40%
            {"index": 3, "relevance_score": 0.20},
            {"index": 4, "relevance_score": 0.10},
        ]

        results = await search_documents(prompt="test", user_email="test@test.com", user_id=1, window_size=5)

        # Cliff truncation must have cut off doc 2, 3, 4, leaving only 2 top documents
        assert len(results) == 2
        assert results[0][0].metadata["id"] == "doc_0"
        assert results[1][0].metadata["id"] == "doc_1"


def test_markdown_table_atomic_protection(monkeypatch):
    """Verify that markdown tables under max_atomic_size are kept as a single atomic chunk."""
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", True)
    table_content = """# 用户权限清单

| 用户ID | 用户名 | 角色 | 状态 | 备注 |
|---|---|---|---|---|
| 1001 | Alice | SuperAdmin | Active | 全局管理员 |
| 1002 | Bob | Developer | Active | 后端工程开发 |
| 1003 | Charlie | Auditor | Pending | 财务审计专员 |
| 1004 | David | Guest | Inactive | 访客权限临时授权 |
"""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(table_content)
        temp_path = f.name

    try:
        chunks = load_and_chunk_document(temp_path, resource_id="res_tbl_1")
        # Should have 1 table chunk (heading is injected as breadcrumb)
        assert len(chunks) == 1
        table_chunk = chunks[0]
        assert table_chunk["block_type"] == "table"
        assert "| 用户ID | 用户名 | 角色 |" in table_chunk["text"]
        assert "| 1004 | David |" in table_chunk["text"]
        assert "[用户权限清单]" in table_chunk["indexing_text"]
        assert not table_chunk["text"].startswith("[用户权限清单]")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_markdown_large_table_repeated_headers(monkeypatch):
    """Verify that oversized markdown tables are sliced row-by-row with repeated headers in each slice."""
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", True)
    monkeypatch.setattr(settings, "MAX_ATOMIC_BLOCK_SIZE", 250)

    header = "| Metric ID | Metric Name | Value | Threshold | Status |\n|---|---|---|---|---|\n"
    rows = [f"| M_{i:03d} | Metric_CPU_Core_{i} | {20 + i}% | 85% | OK |" for i in range(1, 20)]
    table_content = f"# 监控指标大表\n\n{header}" + "\n".join(rows) + "\n"

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(table_content)
        temp_path = f.name

    try:
        chunks = load_and_chunk_document(temp_path, resource_id="res_tbl_large")
        assert len(chunks) > 1
        for idx, c in enumerate(chunks):
            assert c["block_type"] == "table"
            # Every slice must preserve the table header definition
            assert "| Metric ID | Metric Name |" in c["text"]
            assert "|---|---|---|---|---|" in c["text"]
            assert "[监控指标大表]" in c["indexing_text"]
            # Ensure continuity across slices
            assert c["chunk_order"] == idx
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_markdown_code_block_atomic_and_split(monkeypatch):
    """Verify that code blocks preserve language markers and are kept atomic or cleanly sliced."""
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", True)
    monkeypatch.setattr(settings, "MAX_ATOMIC_BLOCK_SIZE", 200)

    code_content = """# 算法核心

```python
def quick_sort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)
```
"""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(code_content)
        temp_path = f.name

    try:
        chunks = load_and_chunk_document(temp_path, resource_id="res_code_1")
        assert len(chunks) > 1
        for c in chunks:
            assert c["block_type"] == "code"
            # Each slice must be wrapped in valid python code fence
            assert c["text"].strip().startswith("```python")
            assert c["text"].strip().endswith("```")
            assert "[算法核心]" in c["indexing_text"]
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_deduplicate_overlap_text():
    from backend.api.services.search import deduplicate_overlap_text

    # Case 1: Overlapping boundary between chunks
    t1 = "检索初筛完成后，需要进行Cross-Encoder精排打分。"
    t2 = "需要进行Cross-Encoder精排打分。精排打分完成后截断长尾噪声。"
    merged = deduplicate_overlap_text(t1, t2)
    assert merged == "检索初筛完成后，需要进行Cross-Encoder精排打分。\n精排打分完成后截断长尾噪声。"

    # Case 2: No overlap
    t3 = "第一章节的内容。"
    t4 = "第二章节的内容。"
    merged2 = deduplicate_overlap_text(t3, t4)
    assert merged2 == "第一章节的内容。\n\n第二章节的内容。"

    # Case 3: Substring containment
    t5 = "全文包含所有信息以及核心逻辑。"
    t6 = "核心逻辑"
    assert deduplicate_overlap_text(t5, t6) == t5


def test_deoverlap_and_merge_adjacent_chunks():
    from backend.api.services.search import deoverlap_and_merge_adjacent_chunks
    from langchain_core.documents import Document

    d1 = Document(page_content="模块A初始化说明。关键配置如下：", metadata={"chunk_group": "res_a", "chunk_order": 1, "id": "chk_1"})
    d2 = Document(page_content="关键配置如下：port=8080, workers=4。", metadata={"chunk_group": "res_a", "chunk_order": 2, "id": "chk_2"})
    d3 = Document(page_content="独立模块B系统说明书。", metadata={"chunk_group": "res_b", "chunk_order": 1, "id": "chk_b1"})
    d4 = Document(page_content="模块A远端日志与监控章节。", metadata={"chunk_group": "res_a", "chunk_order": 9, "id": "chk_9"})

    results = [(d1, 0.95), (d2, 0.88), (d3, 0.82), (d4, 0.75)]
    merged = deoverlap_and_merge_adjacent_chunks(results)

    # d1 and d2 are adjacent in res_a (order 1 & 2) -> merged into 1 doc
    # d3 is res_b -> separate doc
    # d4 is res_a order 9 (far from 1, 2) -> separate doc
    assert len(merged) == 3

    merged_d1_d2 = merged[0][0]
    assert "模块A初始化说明。关键配置如下：" in merged_d1_d2.page_content
    assert "port=8080, workers=4。" in merged_d1_d2.page_content
    assert merged_d1_d2.metadata.get("chunk_order_span") == [1, 2]
    assert merged_d1_d2.metadata.get("merged_chunks") == ["chk_1", "chk_2"]

    assert merged[1][0].metadata["id"] == "chk_b1"
    assert merged[2][0].metadata["id"] == "chk_9"


def test_arrange_lost_in_the_middle():
    from backend.api.services.search import arrange_lost_in_the_middle

    # 5 items: [0, 1, 2, 3, 4] sorted best to worst
    items = ["item_0", "item_1", "item_2", "item_3", "item_4"]
    reordered = arrange_lost_in_the_middle(items)

    # Best (item_0) at index 0, 2nd best (item_1) at index -1
    # 3rd best (item_2) at index 1, 4th best (item_3) at index -2
    # 5th (item_4) in the very middle
    assert reordered == ["item_0", "item_2", "item_4", "item_3", "item_1"]

    # 3 items
    items3 = ["top1", "top2", "top3"]
    assert arrange_lost_in_the_middle(items3) == ["top1", "top3", "top2"]

    # <= 2 items untouched
    assert arrange_lost_in_the_middle(["a", "b"]) == ["a", "b"]
    assert arrange_lost_in_the_middle(["a"]) == ["a"]


@pytest.mark.asyncio
async def test_micro_batch_embedder_aggregation():
    from backend.core.micro_batch_embedder import MicroBatchEmbedder

    call_batches = []

    class MockBaseEmbedder:
        def embed_documents(self, texts):
            call_batches.append(list(texts))
            # Return deterministic dummy vectors: len == len(texts)
            return [[float(len(t))] * 4 for t in texts]

        def embed_query(self, text):
            return [1.0] * 4

    # Micro batch size 8, timeout 40ms
    embedder = MicroBatchEmbedder(MockBaseEmbedder(), batch_size=8, timeout_ms=40.0)

    # Launch 10 concurrent requests with varying text counts
    async def request_task(text_list):
        return await embedder.embed_documents_async(text_list)

    tasks = [
        request_task([f"chunk_{i}_a", f"chunk_{i}_b"])
        for i in range(5)
    ]
    # Total 10 chunks submitted concurrently
    results = await asyncio.gather(*tasks)

    # Verify that all 10 chunks were resolved properly
    assert len(results) == 5
    for sub in results:
        assert len(sub) == 2
        assert len(sub[0]) == 4

    # Verify that aggregator batched them (first batch had up to 8 chunks)
    assert len(call_batches) >= 1
    assert any(len(b) > 2 for b in call_batches)


@pytest.mark.asyncio
async def test_micro_batch_embedder_timeout_flush():
    from backend.core.micro_batch_embedder import MicroBatchEmbedder

    call_batches = []

    class MockBaseEmbedder:
        def embed_documents(self, texts):
            call_batches.append(list(texts))
            return [[0.5] * 4 for _ in texts]

        def embed_query(self, text):
            return [0.5] * 4

    # Large batch size 64, small timeout 25ms
    embedder = MicroBatchEmbedder(MockBaseEmbedder(), batch_size=64, timeout_ms=25.0)

    # Submit just 1 item
    t0 = asyncio.get_event_loop().time()
    res = await embedder.embed_documents_async(["single chunk"])
    duration = (asyncio.get_event_loop().time() - t0) * 1000.0

    assert len(res) == 1
    assert res[0] == [0.5] * 4
    # Flushed promptly after timeout window (under 500ms)
    assert duration < 500.0
    assert len(call_batches) == 1
    assert call_batches[0] == ["single chunk"]


@pytest.mark.asyncio
async def test_durable_jobs_checkpoint_transitions():
    import json
    from backend.worker.durable_jobs import _save_checkpoint
    from backend.api.models import IngestionJob
    from unittest.mock import AsyncMock

    mock_session = AsyncMock()
    job = IngestionJob(id=1, payload=json.dumps({"file_name": "test.pdf"}))

    await _save_checkpoint(mock_session, job, "PARSED", {"char_count": 1024})
    p1 = json.loads(job.payload)
    assert p1["checkpoint_stage"] == "PARSED"
    assert p1["checkpoint_data"]["char_count"] == 1024

    await _save_checkpoint(mock_session, job, "EMBEDDED")
    p2 = json.loads(job.payload)
    assert p2["checkpoint_stage"] == "EMBEDDED"

    await _save_checkpoint(mock_session, job, "PERSISTED")
    p3 = json.loads(job.payload)
    assert p3["checkpoint_stage"] == "PERSISTED"



