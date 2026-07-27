import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document
from backend.config import settings
from backend.database import sync_engine, ChunkMappingTable, Base
from sqlalchemy.orm import Session
from backend.core.utils import record_chunk_mappings, _process_chunks_with_mapping
from backend.api.services.search import _expand_context

@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(sync_engine)
    with Session(sync_engine) as session:
        session.query(ChunkMappingTable).delete()
        session.commit()
    yield
    with Session(sync_engine) as session:
        session.query(ChunkMappingTable).delete()
        session.commit()

def test_chunk_mapping_write_and_read():
    mappings = [
        {"chunk_id": "c1", "chunk_group": "g1", "chunk_order": 0, "resource_id": "r1"},
        {"chunk_id": "c2", "chunk_group": "g1", "chunk_order": 1, "resource_id": "r1"},
    ]
    record_chunk_mappings(mappings)
    
    with Session(sync_engine) as session:
        rows = session.query(ChunkMappingTable).filter_by(chunk_group="g1").order_by(ChunkMappingTable.chunk_order).all()
        assert len(rows) == 2
        assert rows[0].chunk_id == "c1"
        assert rows[1].chunk_id == "c2"

def test_process_chunks_with_mapping_disabled(monkeypatch):
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", False)
    raw = [{"text": "hello", "page_number": 1}]
    out = _process_chunks_with_mapping(raw, "res1")
    assert out == raw
    assert "chunk_id" not in out[0]

def test_process_chunks_with_mapping_enabled(monkeypatch):
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", True)
    raw = [{"text": "hello", "page_number": 1}, {"text": "world", "page_number": 1}]
    out = _process_chunks_with_mapping(raw, "res1")
    assert len(out) == 2
    assert "chunk_id" in out[0]
    assert out[0]["chunk_group"] == "res1"
    assert out[0]["chunk_order"] == 0
    assert out[1]["chunk_order"] == 1

def test_expand_context_disabled(monkeypatch):
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", False)
    doc = Document(page_content="orig", metadata={"id": "c1"})
    res = [(doc, 0.9)]
    out = _expand_context(res, window_size=5)
    assert len(out) == 1
    assert out[0][0].page_content == "orig"

def test_expand_context_fail_open_not_in_db(monkeypatch):
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", True)
    doc = Document(page_content="orig", metadata={"id": "nonexistent_id"})
    res = [(doc, 0.9)]
    out = _expand_context(res, window_size=5)
    assert len(out) == 1
    assert out[0][0].page_content == "orig"

def test_expand_context_success(monkeypatch):
    monkeypatch.setattr(settings, "CHUNK_EXPAND_ENABLED", True)
    monkeypatch.setattr(settings, "CHUNK_EXPAND_WINDOW", 1)
    
    mappings = [
        {"chunk_id": "c0", "chunk_group": "g1", "chunk_order": 0, "resource_id": "r1"},
        {"chunk_id": "c1", "chunk_group": "g1", "chunk_order": 1, "resource_id": "r1"},
        {"chunk_id": "c2", "chunk_group": "g1", "chunk_order": 2, "resource_id": "r1"},
    ]
    record_chunk_mappings(mappings)
    
    mock_fetch = MagicMock(return_value={
        "c0": "First part.",
        "c1": "Middle part.",
        "c2": "Last part."
    })
    
    with patch("backend.api.services.search._fetch_chunks_by_ids", mock_fetch):
        doc = Document(page_content="Middle part.", metadata={"id": "c1"})
        res = [(doc, 0.85)]
        out = _expand_context(res, window_size=5)
        assert len(out) == 1
        merged_text = out[0][0].page_content
        assert "First part." in merged_text
        assert "Middle part." in merged_text
        assert "Last part." in merged_text
        assert out[0][0].metadata["expanded_from_chunk"] == "c1"
