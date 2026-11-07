"""Unit and integration tests for durable job retry, scanned PDF OCR fallback, and error handling."""
import asyncio
import os
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database import Base
from backend.api.models import User, FileUpload, Note, Link, IngestionJob, JobStatus, ProcessingStatus
from backend.worker.durable_jobs import execute_job, _execute_document
from backend.core.fts5_utils import insert_fts5, match_fts5
from backend.worker.url_processor_recursive import crawl_url


@pytest.fixture
def async_db(tmp_path):
    db_path = tmp_path / "test_durable.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    
    from sqlalchemy import create_engine
    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    async_engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    return session_maker


@pytest.mark.asyncio
async def test_job_failed_extraction_marks_job_failed_not_succeeded(async_db, tmp_path):
    """Bug 1: Verify that when extraction fails, job is marked FAILED (after max attempts), never SUCCEEDED."""
    test_file = tmp_path / "corrupted.docx"
    test_file.write_bytes(b"corrupt")

    async with async_db() as session:
        file_row = FileUpload(
            id=10,
            filename="corrupted.docx",
            original_filename="corrupted.docx",
            file_path=str(test_file),
            file_url="/file/corrupted.docx",
            status=ProcessingStatus.PENDING,
            user_id=1,
        )
        job = IngestionJob(
            id=1,
            job_type="file",
            resource_id=10,
            user_id=1,
            user_email="user@test.com",
            status=JobStatus.RUNNING,
            attempts=3,
            max_attempts=3,
            payload='{"file_path": "' + str(test_file) + '", "file_name": "corrupted.docx", "file_url": "/file/corrupted.docx"}',
        )
        session.add(file_row)
        session.add(job)
        await session.commit()

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=async_db()), \
         patch("backend.parsers.parse_document", side_effect=ValueError("Corrupt document")):

        await execute_job(1)

    async with async_db() as session:
        result = await session.get(IngestionJob, 1)
        assert result.status == JobStatus.FAILED
        assert "Corrupt document" in (result.last_error or "")
        
        db_file = await session.get(FileUpload, 10)
        assert db_file.status == ProcessingStatus.FAILED


@pytest.mark.asyncio
async def test_job_retry_on_first_failure(async_db, tmp_path):
    """Verify that when attempts < max_attempts, job transitions back to PENDING for retry."""
    test_file = tmp_path / "flaky.docx"
    test_file.write_bytes(b"flaky")

    async with async_db() as session:
        file_row = FileUpload(
            id=20,
            filename="flaky.docx",
            original_filename="flaky.docx",
            file_path=str(test_file),
            file_url="/file/flaky.docx",
            status=ProcessingStatus.PENDING,
            user_id=1,
        )
        job = IngestionJob(
            id=2,
            job_type="file",
            resource_id=20,
            user_id=1,
            user_email="user@test.com",
            status=JobStatus.RUNNING,
            attempts=1,
            max_attempts=3,
            payload='{"file_path": "' + str(test_file) + '", "file_name": "flaky.docx", "file_url": "/file/flaky.docx"}',
        )
        session.add(file_row)
        session.add(job)
        await session.commit()

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=async_db()), \
         patch("backend.worker.durable_jobs.notify_workers") as mock_notify, \
         patch("backend.parsers.parse_document", side_effect=RuntimeError("Transient error")):

        await execute_job(2)
        mock_notify.assert_called_once()

    async with async_db() as session:
        result = await session.get(IngestionJob, 2)
        assert result.status == JobStatus.PENDING
        assert "Transient error" in (result.last_error or "")


@pytest.mark.asyncio
async def test_scanned_pdf_ocr_fallback(monkeypatch):
    """Bug 2: Verify scanned PDF (ValueError empty content) routes into OCR fallback."""
    monkeypatch.setattr(settings, "OCR_MODE", "auto")
    monkeypatch.setattr(settings, "OCR_MIN_CHARS", 40)

    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 99
    m_job.user_email = "test@example.com"
    m_job.user_id = 1

    payload = {
        "file_path": "scanned.pdf",
        "file_name": "scanned.pdf",
        "file_url": "/file/scanned.pdf",
    }

    with patch("backend.parsers.parse_document", side_effect=ValueError("PDF text extraction returned empty content (scanned/image-only PDFs are not supported yet)")), \
         patch("backend.core.pdf_render.render_pdf_pages", return_value=[b"fake_png"]) as m_render, \
         patch("backend.core.ocr_client.ocr_image_bytes", new_callable=AsyncMock, return_value="Scanned Text Recovered") as m_ocr, \
         patch("backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store") as m_add, \
         patch("backend.worker.durable_jobs._mark_resource_status") as m_mark:

        await _execute_document(m_session, m_job, payload)

        m_render.assert_called_once()
        m_ocr.assert_called_once_with(b"fake_png")
        m_add.assert_called_once()
        args, _ = m_add.call_args
        assert args[0] == "scanned.pdf.ocr.md"

        if os.path.exists("scanned.pdf.ocr.md"):
            os.remove("scanned.pdf.ocr.md")


@pytest.mark.asyncio
async def test_recursive_crawl_marks_failed_on_exception(async_db):
    """Bug 3: Verify crawler marks db_link as FAILED on exception."""
    user = User(id=1, email="test@test.com", username="tester", is_active=True)

    class MockDoc:
        page_content = "some text"
        metadata = {"source": "https://example.com/bad", "title": "Bad Page"}

    async def mock_alazy_load(self):
        yield MockDoc()

    with patch("backend.worker.url_processor_recursive.async_session_maker", return_value=async_db()), \
         patch("backend.worker.url_processor_recursive.RecursiveUrlLoader.alazy_load", mock_alazy_load), \
         patch("backend.worker.url_processor_recursive.vector_store.add_link_content_to_vector_store", side_effect=Exception("Vector store unavailable")), \
         patch("backend.worker.url_processor_recursive.recursive_url_processing_queue.task_done") as m_done:

        await crawl_url("https://example.com/bad", user, {})
        m_done.assert_called_once()

    async with async_db() as session:
        from sqlalchemy import select
        res = await session.execute(select(Link).where(Link.url == "https://example.com/bad"))
        link = res.scalars().first()
        assert link is not None
        assert link.status == ProcessingStatus.FAILED
        assert "Vector store unavailable" in (link.error_message or "")


def test_fts5_insert_creates_table_on_no_such_table():
    """Bug 4: Verify insert_fts5 creates table on OperationalError."""
    conn = sqlite3.connect(":memory:")
    # chunks_fts does NOT exist initially
    insert_fts5(
        conn,
        chunk_id="chk_1",
        title="Test Document",
        filename="test.txt",
        page_content="Hello FTS5 world content",
        user_id="1",
        source_type="file",
        belongs_to="user@test.com",
        resource_id="10",
    )

    # Search should now succeed because table was auto-created
    results = match_fts5(conn, "Hello", user_id="1", belongs_to="user@test.com")
    assert len(results) == 1
    assert results[0]["chunk_id"] == "chk_1"
    conn.close()
