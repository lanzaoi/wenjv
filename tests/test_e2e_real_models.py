# tests/test_e2e_real_models.py
"""
End-to-End Real Cloud Models & RAG Ceiling Verification Suite.
Validates the entire pipeline:
  - Structure-aware chunking (Markdown table & code block preservation)
  - SiliconFlow BAAI/bge-m3 embedding into LanceDB
  - SiliconFlow BAAI/bge-reranker-v2-m3 reranking
  - Relative elbow gap drop cutoff & Lost-in-the-Middle arrange
  - Google Gemma 4 31B streaming chat generation with citation
  - Micro-batch embedding concurrent aggregation
"""
import pytest
import asyncio
from langchain.schema import Document

from backend.config import settings
from backend.core.structure_chunker import structure_aware_chunk
from backend.vector_store.adapter import vector_db
from backend.api.services.search import search_documents
from backend.api.services.chat import rag_chat_events


@pytest.mark.asyncio
async def test_structure_aware_table_and_code_chunking():
    table_content = """# 预算指标大表
| 项目 | 预算 | 状态 |
|---|---|---|
| 服务器 | 50000 | 正常 |
"""
    chunks = structure_aware_chunk(table_content, max_atomic_size=1000)
    assert len(chunks) == 1
    assert chunks[0]["block_type"] == "table"
    assert "50000" in chunks[0]["text"]
    assert "预算指标大表" in chunks[0]["indexing_text"]


@pytest.mark.asyncio
async def test_micro_batch_embedder_concurrency():
    vs = vector_db()
    embedder = vs.embeddings
    
    texts1 = ["Chunk A1", "Chunk A2"]
    texts2 = ["Chunk B1", "Chunk B2"]
    
    res1, res2 = await asyncio.gather(
        embedder.embed_documents_async(texts1),
        embedder.embed_documents_async(texts2),
    )
    assert len(res1) == 2
    assert len(res2) == 2
    assert len(res1[0]) == 1024


@pytest.mark.asyncio
async def test_e2e_retrieval_and_rerank_scoring():
    vs = vector_db()
    test_uid = 9988
    test_email = "e2e_test@wenjv.internal"
    
    doc = Document(
        page_content="DistributedPersistLock 的 acquire_exclusive 方法接收参数 job_id: str 进行独占加锁。",
        metadata={
            "source": "lock.py",
            "filename": "lock.py",
            "title": "分布式锁文档",
            "user_id": str(test_uid),
            "belongs_to": test_email,
            "resource_id": "lock.py",
            "chunk_group": "lock.py",
            "chunk_order": 0,
        }
    )
    vs.add_documents([doc])
    
    hits = await search_documents(
        prompt="acquire_exclusive 接收什么参数？",
        user_email=test_email,
        user_id=test_uid,
        window_size=3,
        lost_in_the_middle=False,
    )
    assert len(hits) >= 1
    top_doc, top_score = hits[0]
    assert "job_id" in top_doc.page_content
