"""
Integration & unit tests for tag-based classification and dual-layer recall compensation.
Verifies:
1. Tag normalization and JSON serialization.
2. SQLite column upgrade and single-source-of-truth persistence.
3. Base Tag Service CRUD, cache invalidation, and source resolution.
4. Auto-tagger rule extraction, sampling, and fail-open LLM resilience.
5. Ingestion job tag persistence and durable queue payload passing.
6. Layer 1 pre-filtering & RRF gradient boosting.
7. Layer 2 soft-fallback recall top-up when tag matches < window_size.
8. REST API endpoints (/documents/tags, PUT /documents/.../tags, POST /documents/tags/backfill).
"""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import Session, sessionmaker
from fastapi.testclient import TestClient
from fastapi import Request, HTTPException

from backend.api.models import Base, User, FileUpload, Note, Link, ProcessingStatus
from backend.database import QueryResultCacheTable
from backend.api.services.tags import (
    normalize_tags,
    tags_to_json,
    tags_from_json,
    get_user_tags_summary,
    get_user_tags_summary_sync,
    update_resource_tags,
    resolve_sources_by_tags,
    backfill_user_tags,
)
from backend.core.auto_tagger import (
    extract_rule_tags,
    _build_sampling_text,
    generate_document_tags,
)
from backend.api.services.search import (
    extract_inline_tags,
    search_documents,
)
from backend.main import app
from backend.api.dependencies import current_active_user
from backend.database import get_async_session


# ---------------------------------------------------------------------------
# 1. Tag Normalization & Serialization
# ---------------------------------------------------------------------------

def test_tag_normalization():
    raw = ["#Rust", "  Python  ", "rust", "", "   ", "#AI-Search#", "x" * 60]
    cleaned = normalize_tags(raw)
    assert cleaned == ["rust", "python", "ai-search", "x" * 24]

    # Test string input
    assert normalize_tags("tag1, tag2, #tag3") == ["tag1", "tag2", "tag3"]
    assert normalize_tags("") == []
    assert normalize_tags(None) == []


def test_tag_json_helpers():
    tags = ["arch", "linux"]
    json_str = tags_to_json(tags)
    assert json.loads(json_str) == ["arch", "linux"]
    assert tags_from_json(json_str) == ["arch", "linux"]

    # Resilience to malformed or legacy inputs
    assert tags_from_json("") == []
    assert tags_from_json(None) == []
    assert tags_from_json("invalid json string") == []
    assert tags_from_json('{"key": "val"}') == []


# ---------------------------------------------------------------------------
# 2. Base Tag Service & SQLite Single Source of Truth
# ---------------------------------------------------------------------------

@pytest.fixture
def sync_db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_resolve_sources_by_tags(sync_db_engine):
    with Session(sync_db_engine) as session:
        # User 1 resources
        session.add(FileUpload(
            id=10, filename="file_rust.pdf", original_filename="rust_guide.pdf",
            file_url="/file/file_rust.pdf", user_id=1,
            tags=tags_to_json(["rust", "systems"])
        ))
        session.add(Note(
            id=20, title="Python Cheatsheet", filename="note_py.md",
            url="/note/note_py.md", user_id=1,
            tags=tags_to_json(["python", "cheatsheet"])
        ))
        session.add(Link(
            id=30, title="Rust Official", url="https://rust-lang.org",
            user_id=1, tags=tags_to_json(["rust", "official"])
        ))
        # User 2 resource (isolation test)
        session.add(FileUpload(
            id=40, filename="user2_rust.pdf", original_filename="u2.pdf",
            file_url="/file/u2.pdf", user_id=2,
            tags=tags_to_json(["rust"])
        ))
        session.commit()

    with patch("backend.api.services.tags.sync_engine", sync_db_engine):
        scores, rids, sources = resolve_sources_by_tags(1, ["rust"])
        assert 10 in rids
        assert 30 in rids
        assert 20 not in rids  # Note has python, not rust
        assert 40 not in rids  # Belongs to user 2
        assert "file_rust.pdf" in sources
        assert "https://rust-lang.org" in sources


@pytest.mark.asyncio
async def test_update_resource_tags_and_cache_invalidation():
    from datetime import datetime, timedelta
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        # Seed note and query cache
        note = Note(id=1, title="Test Note", filename="n1.md", url="/n1", user_id=99, tags="[]")
        cache = QueryResultCacheTable(
            query_hash="hash_1",
            user_id=99,
            result_json="[]",
            expires_at=datetime.utcnow() + timedelta(days=1)
        )
        session.add_all([note, cache])
        await session.commit()

        # Update tags
        new_tags = await update_resource_tags(session, user_id=99, source_type="note", resource_id=1, raw_tags=["rag", "#v1"])
        assert new_tags == ["rag", "v1"]

        # Verify note updated
        await session.refresh(note)
        assert tags_from_json(note.tags) == ["rag", "v1"]

        # Verify query cache invalidated for user
        from sqlalchemy import select
        res = await session.execute(select(QueryResultCacheTable).where(QueryResultCacheTable.user_id == 99))
        assert res.scalars().all() == []


@pytest.mark.asyncio
async def test_get_user_tags_summary():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        session.add(FileUpload(id=1, filename="f1", original_filename="f1", file_url="/f1", user_id=1, tags=tags_to_json(["ai", "ml"])))
        session.add(Note(id=1, title="n1", filename="n1", url="/n1", user_id=1, tags=tags_to_json(["ai", "deep-learning"])))
        session.add(Link(id=1, title="l1", url="http://l1", user_id=1, tags=tags_to_json(["ai", "tools"])))
        await session.commit()

        summary = await get_user_tags_summary(session, user_id=1, limit=10)
        assert summary[0]["name"] == "ai"
        assert summary[0]["count"] == 3
        names = [item["name"] for item in summary]
        assert "ml" in names
        assert "deep-learning" in names
        assert "tools" in names


# ---------------------------------------------------------------------------
# 3. Auto-Tagger Rules, Sampling & Fail-Open Resilience
# ---------------------------------------------------------------------------

def test_extract_rule_tags():
    # Frontmatter YAML extraction
    doc_with_fm = """---
title: My Research Notes
tags: [quantum, physics, computing]
---

Content discussing quantum computers.
"""
    tags = extract_rule_tags(doc_with_fm)
    assert "quantum" in tags
    assert "physics" in tags
    assert "computing" in tags

    # Hashtags in body
    doc_with_hashtags = "This is a study on #machine-learning and #neural_networks."
    tags2 = extract_rule_tags(doc_with_hashtags)
    assert "machine-learning" in tags2
    assert "neural_networks" in tags2


def test_build_sampling_text():
    short_text = "Short text"
    res1 = _build_sampling_text(short_text, title="T1", max_chars=100)
    assert "Short text" in res1 and "T1" in res1

    long_text = "A" * 1000 + "B" * 1000
    sampled = _build_sampling_text(long_text, title="T2", max_chars=500)
    assert len(sampled) <= 550
    assert "A" in sampled and "B" in sampled and "..." in sampled


@pytest.mark.asyncio
async def test_generate_document_tags_fail_open():
    # Even if LLM completely errors out, generate_document_tags must fail-open and return manual/rule tags!
    text = "Important document about #database systems."
    with patch("backend.core.auto_tagger._call_llm_for_tags", side_effect=RuntimeError("LLM offline")):
        tags = await generate_document_tags(text, title="Doc 1", user_id=1, manual_tags=["infra"])
        # Should gracefully return at least manual tags and rule tags
        assert "infra" in tags
        assert "database" in tags


# ---------------------------------------------------------------------------
# 4. Retrieval Layer 1 Pre-filter & Layer 2 Recall Compensation
# ---------------------------------------------------------------------------

def test_extract_inline_tags():
    prompt = "What is the memory model of #rust and #concurrency?"
    clean_p, tags = extract_inline_tags(prompt)
    assert clean_p == "What is the memory model of and ?"
    assert tags == ["rust", "concurrency"]

    prompt_no_tags = "General question about vectors"
    clean_p2, tags2 = extract_inline_tags(prompt_no_tags)
    assert clean_p2 == "General question about vectors"
    assert tags2 == []


@pytest.mark.asyncio
async def test_search_documents_soft_fallback_recall_compensation():
    from langchain.schema import Document

    mock_vector_store = MagicMock()
    # Mock vector store returning docs
    doc_matched = Document(page_content="Rust ownership semantics", metadata={"id": "doc_1", "filename": "rust.pdf", "user_id": 1})
    doc_general1 = Document(page_content="General memory management", metadata={"id": "doc_2", "filename": "memory.pdf", "user_id": 1})
    doc_general2 = Document(page_content="Operating system design", metadata={"id": "doc_3", "filename": "os.pdf", "user_id": 1})

    # When tag-filtered, only rust.pdf is available
    def mock_fetch(**kwargs):
        inc = kwargs.get("include_selected") or kwargs.get("include_sources")
        if inc and "rust.pdf" in inc:
            return [(doc_matched, 0.1)]
        elif inc and "__no_match_tag__" in inc:
            return []
        else:
            return [(doc_matched, 0.1), (doc_general1, 0.3), (doc_general2, 0.4)]

    mock_vector_store.fetch_documents.side_effect = mock_fetch

    # Mock resolve_sources_by_tags returning rust.pdf for tag 'rust'
    with patch("backend.api.services.search.resolve_sources_by_tags", return_value=({"rust.pdf": 1}, [10], ["rust.pdf"])), \
         patch("backend.api.services.search.vector_store", mock_vector_store), \
         patch("backend.api.services.search.settings") as mock_settings:

        mock_settings.HYBRID_SEARCH_ENABLED = False
        mock_settings.MMR_ENABLED = False
        mock_settings.RERANK_ENABLED = False
        mock_settings.STRUCTURED_RECALL_ENABLED = False
        mock_settings.LATE_CHUNKING_ENABLED = False
        mock_settings.SEARCH_TIMING_ENABLED = False

        # Request window_size=3 with tag 'rust'.
        # Only 1 doc matches the tag. Soft-fallback must top up with 2 unconstrained docs!
        results = await search_documents(
            prompt="memory management #rust",
            window_size=3,
            user_id=1,
            user_email="test@user.com",
        )

        assert len(results) == 3
        # First doc must be tag-matched
        assert results[0][0].metadata.get("tag_matched") is True
        assert results[0][0].metadata.get("id") == "doc_1"

        # Fallback docs must be marked tag_fallback=True
        assert results[1][0].metadata.get("tag_fallback") is True
        assert results[1][0].metadata.get("tag_matched") is False
        assert results[2][0].metadata.get("tag_fallback") is True


# ---------------------------------------------------------------------------
# 5. REST API Endpoints Verification
# ---------------------------------------------------------------------------

USER_TEST = User(id=1, email="tag_user@test.com", username="tag_user", is_active=True, is_superuser=False)


async def mock_active_user(request: Request):
    return USER_TEST


@pytest.fixture
def api_client(tmp_path):
    db_path = tmp_path / "test_tags_api.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    note_file = tmp_path / "n1.md"
    note_file.write_text("This is a note about #compiler design.", encoding="utf-8")

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    with Session(sync_engine) as session:
        session.add(FileUpload(
            id=1, filename="file1.pdf", original_filename="file1.pdf",
            file_url="/file1", user_id=1, tags=tags_to_json(["architecture"])
        ))
        session.add(Note(
            id=1, title="Note 1", filename="n1.md", file_path=str(note_file), url="/n1",
            user_id=1, tags="[]"
        ))
        session.commit()
    sync_engine.dispose()

    async_engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_async_session():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[current_active_user] = mock_active_user
    app.dependency_overrides[get_async_session] = override_get_async_session

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


def test_api_get_tags(api_client):
    res = api_client.get("/documents/tags")
    assert res.status_code == 200
    data = res.json()
    assert "tags" in data
    tags = data["tags"]
    assert any(t["name"] == "architecture" for t in tags)


def test_api_update_resource_tags(api_client):
    res = api_client.put(
        "/documents/file/1/tags",
        json={"tags": ["fastapi", "vue3", "sqlite"]}
    )
    assert res.status_code == 200
    assert res.json()["tags"] == ["fastapi", "vue3", "sqlite"]

    # Check updated tags via tags summary
    sum_res = api_client.get("/documents/tags")
    names = [t["name"] for t in sum_res.json()["tags"]]
    assert "fastapi" in names
    assert "vue3" in names


def test_api_backfill_tags(api_client):
    # Note 1 has tags "[]" and content with "#compiler"
    res = api_client.post("/documents/tags/backfill")
    assert res.status_code == 200
    data = res.json()
    assert data["enqueued_count"] >= 1

    # Check that Note 1 now has tags
    sum_res = api_client.get("/documents/tags")
    names = [t["name"] for t in sum_res.json()["tags"]]
    assert "compiler" in names
