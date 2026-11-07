"""Adversarial challenge tests for Milestone 2 deliverables.

Targeting:
1. Durable jobs failure handling (simulate document parsing crashes, verify job transitions to FAILED, never SUCCEEDED)
2. Scanned PDF OCR routing (0 extractable chars triggers OCR without unhandled ValueError, handling of OCR failure & blank pages)
3. Recursive crawler resilience (unparseable / failing URLs mark link as FAILED, queue worker does not hang or deadlock)
"""
import asyncio
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, create_engine

from backend.config import settings
from backend.database import Base
from backend.api.models import (
    User,
    FileUpload,
    Note,
    Link,
    IngestionJob,
    JobStatus,
    ProcessingStatus,
)
from backend.worker.durable_jobs import execute_job, _execute_document
from backend.worker.url_processor_recursive import (
    crawl_url,
    process_recursive_url_queue,
    recursive_url_processing_queue,
)


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_adversarial.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    async_engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    return session_maker


# ============================================================================
# 1. DURABLE JOBS FAILURE HANDLING ADVERSARIAL TESTS
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("crash_exception", [
    ValueError("Corrupt PDF header / invalid trailer"),
    RuntimeError("Parser native segfault simulation"),
    OSError("I/O failure reading storage volume"),
    MemoryError("Out of memory parsing mammoth document"),
    Exception("Unknown unexpected parser crash"),
])
async def test_adversarial_document_parsing_crash_marks_failed_never_succeeded(
    test_db, tmp_path, crash_exception
):
    """Stress test: Any document parser crash MUST transition job to FAILED (when attempts >= max)
    and NEVER leave the job in SUCCEEDED or unhandled state.
    """
    doc_file = tmp_path / "adversarial_crash.pdf"
    doc_file.write_bytes(b"%PDF-1.4 corrupt data")

    async with test_db() as session:
        file_row = FileUpload(
            id=101,
            filename="adversarial_crash.pdf",
            original_filename="adversarial_crash.pdf",
            file_path=str(doc_file),
            file_url="/file/adversarial_crash.pdf",
            status=ProcessingStatus.PENDING,
            user_id=1,
        )
        job = IngestionJob(
            id=101,
            job_type="file",
            resource_id=101,
            user_id=1,
            user_email="adversary@test.com",
            status=JobStatus.RUNNING,
            attempts=3,
            max_attempts=3,
            payload=(
                '{"file_path": "' + str(doc_file) + '", '
                '"file_name": "adversarial_crash.pdf", '
                '"file_url": "/file/adversarial_crash.pdf"}'
            ),
        )
        session.add(file_row)
        session.add(job)
        await session.commit()

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=test_db()), \
         patch("backend.parsers.parse_document", side_effect=crash_exception):

        # Execute durable job
        await execute_job(101)

    async with test_db() as session:
        result_job = await session.get(IngestionJob, 101)
        assert result_job is not None
        # Assert strictly that job is NEVER SUCCEEDED
        assert result_job.status != JobStatus.SUCCEEDED
        assert result_job.status == JobStatus.FAILED
        assert result_job.finished_at is not None
        assert result_job.last_error is not None
        assert str(crash_exception) in result_job.last_error or type(crash_exception).__name__ in result_job.last_error

        result_file = await session.get(FileUpload, 101)
        assert result_file is not None
        assert result_file.status == ProcessingStatus.FAILED
        assert result_file.error_message is not None


@pytest.mark.asyncio
async def test_adversarial_vector_store_failure_marks_job_failed(test_db, tmp_path):
    """Stress test: If vector store fails during ingestion, job MUST fail, never succeed."""
    doc_file = tmp_path / "valid.txt"
    doc_file.write_text("Valid text content for vector store")

    async with test_db() as session:
        file_row = FileUpload(
            id=102,
            filename="valid.txt",
            original_filename="valid.txt",
            file_path=str(doc_file),
            file_url="/file/valid.txt",
            status=ProcessingStatus.PENDING,
            user_id=1,
        )
        job = IngestionJob(
            id=102,
            job_type="file",
            resource_id=102,
            user_id=1,
            user_email="adversary@test.com",
            status=JobStatus.RUNNING,
            attempts=3,
            max_attempts=3,
            payload=(
                '{"file_path": "' + str(doc_file) + '", '
                '"file_name": "valid.txt", '
                '"file_url": "/file/valid.txt"}'
            ),
        )
        session.add(file_row)
        session.add(job)
        await session.commit()

    mock_chunk = MagicMock()
    mock_chunk.text = "Valid text content"

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=test_db()), \
         patch("backend.parsers.parse_document", return_value=[mock_chunk]), \
         patch("backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store", side_effect=RuntimeError("Vector DB disk full")):

        await execute_job(102)

    async with test_db() as session:
        result_job = await session.get(IngestionJob, 102)
        assert result_job.status == JobStatus.FAILED
        assert result_job.status != JobStatus.SUCCEEDED
        assert "Vector DB disk full" in (result_job.last_error or "")


@pytest.mark.asyncio
async def test_adversarial_retry_lifecycle_to_permanent_failure(test_db, tmp_path):
    """Stress test: Verify state machine transitions from PENDING -> RUNNING -> PENDING (retry) -> FAILED."""
    doc_file = tmp_path / "flaky_doc.docx"
    doc_file.write_bytes(b"content")

    async with test_db() as session:
        file_row = FileUpload(
            id=103,
            filename="flaky_doc.docx",
            original_filename="flaky_doc.docx",
            file_path=str(doc_file),
            file_url="/file/flaky_doc.docx",
            status=ProcessingStatus.PENDING,
            user_id=1,
        )
        job = IngestionJob(
            id=103,
            job_type="file",
            resource_id=103,
            user_id=1,
            user_email="adversary@test.com",
            status=JobStatus.RUNNING,
            attempts=1,
            max_attempts=2,
            payload=(
                '{"file_path": "' + str(doc_file) + '", '
                '"file_name": "flaky_doc.docx", '
                '"file_url": "/file/flaky_doc.docx"}'
            ),
        )
        session.add(file_row)
        session.add(job)
        await session.commit()

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=test_db()), \
         patch("backend.parsers.parse_document", side_effect=ValueError("Attempt 1 failure")):

        # Attempt 1 (attempts=1, max=2): Should requeue to PENDING
        await execute_job(103)

    async with test_db() as session:
        j1 = await session.get(IngestionJob, 103)
        assert j1.status == JobStatus.PENDING
        assert "Attempt 1 failure" in (j1.last_error or "")

        # Now simulate dispatcher claiming job for Attempt 2
        j1.status = JobStatus.RUNNING
        j1.attempts = 2
        await session.commit()

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=test_db()), \
         patch("backend.parsers.parse_document", side_effect=ValueError("Attempt 2 final failure")):

        # Attempt 2 (attempts=2, max=2): Out of attempts -> FAILED
        await execute_job(103)

    async with test_db() as session:
        j2 = await session.get(IngestionJob, 103)
        assert j2.status == JobStatus.FAILED
        assert j2.status != JobStatus.SUCCEEDED
        assert "Attempt 2 final failure" in (j2.last_error or "")


# ============================================================================
# 2. SCANNED PDF OCR ROUTING ADVERSARIAL TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_scanned_pdf_empty_characters_triggers_ocr_successfully(monkeypatch):
    """Verify that a PDF raising ValueError (0 extractable text) routes cleanly to OCR without unhandled exception."""
    monkeypatch.setattr(settings, "OCR_MODE", "auto")
    monkeypatch.setattr(settings, "OCR_MIN_CHARS", 40)

    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 201
    m_job.user_email = "ocr@test.com"
    m_job.user_id = 1

    payload = {
        "file_path": "scanned_doc.pdf",
        "file_name": "scanned_doc.pdf",
        "file_url": "/file/scanned_doc.pdf",
    }

    # Simulate parser raising the exact scanned PDF exception
    empty_pdf_err = ValueError("PDF text extraction returned empty content (scanned/image-only PDFs are not supported yet)")

    with patch("backend.parsers.parse_document", side_effect=empty_pdf_err) as m_parse, \
         patch("backend.core.pdf_render.render_pdf_pages", return_value=[b"fake_rendered_page"]) as m_render, \
         patch("backend.core.ocr_client.ocr_image_bytes", new_callable=AsyncMock, return_value="Recognized optical character content") as m_ocr, \
         patch("backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store") as m_add, \
         patch("backend.worker.durable_jobs._mark_resource_status") as m_status:

        # Must execute without raising unhandled ValueError
        await _execute_document(m_session, m_job, payload)

        m_render.assert_called_once_with("scanned_doc.pdf", 30)
        m_ocr.assert_called_once_with(b"fake_rendered_page")
        m_add.assert_called_once()
        args, _ = m_add.call_args
        assert args[0] == "scanned_doc.pdf.ocr.md"
        assert args[1] == "scanned_doc.pdf"

        # Check resource marked FINISHED
        m_status.assert_any_call(m_session, m_job, ProcessingStatus.FINISHED, None)

        if os.path.exists("scanned_doc.pdf.ocr.md"):
            os.remove("scanned_doc.pdf.ocr.md")


@pytest.mark.asyncio
async def test_scanned_pdf_ocr_returns_empty_raises_and_marks_failed(monkeypatch):
    """Stress test: Scanned PDF where OCR yields completely empty text (e.g. blank scan).
    Must NOT silently succeed or index empty docs; must fail and raise RuntimeError.
    """
    monkeypatch.setattr(settings, "OCR_MODE", "auto")
    monkeypatch.setattr(settings, "OCR_MIN_CHARS", 40)

    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 202
    m_job.user_email = "ocr@test.com"
    m_job.user_id = 1

    payload = {
        "file_path": "blank_scan.pdf",
        "file_name": "blank_scan.pdf",
        "file_url": "/file/blank_scan.pdf",
    }

    empty_pdf_err = ValueError("PDF text extraction returned empty content")

    with patch("backend.parsers.parse_document", side_effect=empty_pdf_err), \
         patch("backend.core.pdf_render.render_pdf_pages", return_value=[b"blank_png"]), \
         patch("backend.core.ocr_client.ocr_image_bytes", new_callable=AsyncMock, return_value=""), \
         patch("backend.worker.durable_jobs._mark_resource_failed") as m_fail:

        with pytest.raises(RuntimeError) as exc_info:
            await _execute_document(m_session, m_job, payload)

        assert "Scanned PDF OCR returned empty content" in str(exc_info.value)
        assert m_fail.call_count >= 1
        args, _ = m_fail.call_args
        assert "Scanned PDF OCR returned empty content" in args[2]


@pytest.mark.asyncio
async def test_scanned_pdf_rendering_crash_fails_gracefully(monkeypatch):
    """Stress test: PDF render library crashes on corrupt scanned PDF.
    Must mark resource failed and raise RuntimeError.
    """
    monkeypatch.setattr(settings, "OCR_MODE", "auto")

    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 203
    m_job.user_email = "ocr@test.com"
    m_job.user_id = 1

    payload = {
        "file_path": "corrupt_scan.pdf",
        "file_name": "corrupt_scan.pdf",
        "file_url": "/file/corrupt_scan.pdf",
    }

    with patch("backend.parsers.parse_document", side_effect=ValueError("Empty PDF")), \
         patch("backend.core.pdf_render.render_pdf_pages", side_effect=Exception("MuPDF / Poppler crash")), \
         patch("backend.worker.durable_jobs._mark_resource_failed") as m_fail:

        with pytest.raises(RuntimeError) as exc_info:
            await _execute_document(m_session, m_job, payload)

        assert "OCR extraction failed" in str(exc_info.value)
        m_fail.assert_called_once()


@pytest.mark.asyncio
async def test_scanned_pdf_with_ocr_mode_off_raises_value_error(monkeypatch):
    """Verify that when OCR_MODE is 'off', scanned PDF does not run OCR and raises."""
    monkeypatch.setattr(settings, "OCR_MODE", "off")

    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 204
    m_job.user_email = "ocr@test.com"
    m_job.user_id = 1

    payload = {
        "file_path": "no_ocr.pdf",
        "file_name": "no_ocr.pdf",
        "file_url": "/file/no_ocr.pdf",
    }

    with patch("backend.parsers.parse_document", side_effect=ValueError("No text layer")), \
         patch("backend.core.pdf_render.render_pdf_pages") as m_render, \
         patch("backend.worker.durable_jobs._mark_resource_failed") as m_fail:

        with pytest.raises(ValueError):
            await _execute_document(m_session, m_job, payload)

        m_render.assert_not_called()
        m_fail.assert_called_once()


# ============================================================================
# 3. RECURSIVE CRAWLER RESILIENCE & QUEUE LIVENESS ADVERSARIAL TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_recursive_crawler_error_marks_link_failed_and_calls_task_done(test_db):
    """Verify that an error during crawl marks db_link as FAILED and executes task_done."""
    user = User(id=1, email="crawler_adv@test.com", username="crawler_adv", is_active=True)

    class MockDoc:
        page_content = "Corrupt crawled content"
        metadata = {"source": "https://test.bad/page1", "title": "Bad Page"}

    async def mock_alazy_load(self):
        yield MockDoc()

    with patch("backend.worker.url_processor_recursive.async_session_maker", return_value=test_db()), \
         patch("backend.worker.url_processor_recursive.RecursiveUrlLoader.alazy_load", mock_alazy_load), \
         patch("backend.worker.url_processor_recursive.vector_store.add_link_content_to_vector_store", side_effect=RuntimeError("Vector indexing crashed")), \
         patch.object(recursive_url_processing_queue, "task_done") as mock_task_done:

        await crawl_url("https://test.bad/page1", user, {})
        mock_task_done.assert_called_once()

    async with test_db() as session:
        res = await session.execute(select(Link).where(Link.url == "https://test.bad/page1"))
        link = res.scalars().first()
        assert link is not None
        assert link.status == ProcessingStatus.FAILED
        assert "Vector indexing crashed" in (link.error_message or "")


@pytest.mark.asyncio
async def test_recursive_crawler_multi_doc_partial_failure(test_db):
    """Stress test: Stream yields doc1 (success) then doc2 (failure).
    Verify doc1 is FINISHED and doc2 is FAILED, and queue task_done is called.
    """
    user = User(id=1, email="stream_user@test.com", username="stream_user", is_active=True)

    class Doc1:
        page_content = "Good page"
        metadata = {"source": "https://test.site/good", "title": "Good"}

    class Doc2:
        page_content = "Bad page"
        metadata = {"source": "https://test.site/bad", "title": "Bad"}

    async def mock_multi_alazy_load(self):
        yield Doc1()
        yield Doc2()

    call_count = 0
    def mock_add(text, source, title, link_id, email):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ValueError("Failure on second doc")

    with patch("backend.worker.url_processor_recursive.async_session_maker", return_value=test_db()), \
         patch("backend.worker.url_processor_recursive.RecursiveUrlLoader.alazy_load", mock_multi_alazy_load), \
         patch("backend.worker.url_processor_recursive.vector_store.add_link_content_to_vector_store", side_effect=mock_add), \
         patch.object(recursive_url_processing_queue, "task_done") as mock_task_done:

        await crawl_url("https://test.site", user, {})
        mock_task_done.assert_called_once()

    async with test_db() as session:
        res1 = await session.execute(select(Link).where(Link.url == "https://test.site/good"))
        link1 = res1.scalars().first()
        assert link1 is not None
        assert link1.status == ProcessingStatus.FINISHED

        res2 = await session.execute(select(Link).where(Link.url == "https://test.site/bad"))
        link2 = res2.scalars().first()
        assert link2 is not None
        assert link2.status == ProcessingStatus.FAILED
        assert "Failure on second doc" in (link2.error_message or "")


@pytest.mark.asyncio
async def test_recursive_crawler_queue_worker_never_hangs_on_errors(test_db):
    """Stress test: Send a batch of mixed URLs (good, crashing, exception-raising, invalid)
    through the actual queue and verify queue.join() completes cleanly within timeout.
    Guarantees no deadlocks or hung queue workers.
    """
    user = User(id=1, email="queue_adv@test.com", username="queue_adv", is_active=True)

    class MockDoc:
        def __init__(self, url):
            self.page_content = f"Content from {url}"
            self.metadata = {"source": url, "title": f"Title {url}"}

    async def mock_loader_alazy(self):
        url = self.url
        if "network_fail" in url:
            raise ConnectionRefusedError("Simulated connection refused")
        elif "empty" in url:
            return
        yield MockDoc(url)

    def mock_vector_add(text, source, title, link_id, email):
        if "bad_vector" in source:
            raise RuntimeError("Simulated vector DB failure")

    # Start queue processor worker task
    worker_task = asyncio.create_task(process_recursive_url_queue())

    test_urls = [
        "https://example.com/ok_1",
        "https://example.com/network_fail",
        "https://example.com/bad_vector",
        "https://example.com/empty",
        "https://example.com/ok_2",
    ]

    with patch("backend.worker.url_processor_recursive.async_session_maker", side_effect=lambda: test_db()), \
         patch("backend.worker.url_processor_recursive.RecursiveUrlLoader.alazy_load", mock_loader_alazy), \
         patch("backend.worker.url_processor_recursive.vector_store.add_link_content_to_vector_store", side_effect=mock_vector_add):

        for u in test_urls:
            await recursive_url_processing_queue.put((u, user, {}))

        # queue.join() must complete without timing out (timeout=5s)
        try:
            await asyncio.wait_for(recursive_url_processing_queue.join(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("recursive_url_processing_queue.join() timed out! Queue worker hung on error!")
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    # Verify links recorded in database
    async with test_db() as session:
        res_ok = await session.execute(select(Link).where(Link.url == "https://example.com/ok_1"))
        link_ok = res_ok.scalars().first()
        assert link_ok is not None
        assert link_ok.status == ProcessingStatus.FINISHED

        res_bad = await session.execute(select(Link).where(Link.url == "https://example.com/bad_vector"))
        link_bad = res_bad.scalars().first()
        assert link_bad is not None
        assert link_bad.status == ProcessingStatus.FAILED


# ============================================================================
# 4. ADDITIONAL STRESS TESTS: MULTIMODAL, STALE RECLAIM, BOUNDARY CONDITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_image_ingest_failure_marks_failed(test_db, tmp_path):
    """Stress test: Corrupt image file causing ImageExtractionError transitions job to FAILED."""
    img_file = tmp_path / "corrupt.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\ncorrupt_bytes")

    async with test_db() as session:
        file_row = FileUpload(
            id=301,
            filename="corrupt.png",
            original_filename="corrupt.png",
            file_path=str(img_file),
            file_url="/file/corrupt.png",
            status=ProcessingStatus.PENDING,
            user_id=1,
        )
        job = IngestionJob(
            id=301,
            job_type="file",
            resource_id=301,
            user_id=1,
            user_email="adversary@test.com",
            status=JobStatus.RUNNING,
            attempts=3,
            max_attempts=3,
            payload=(
                '{"file_path": "' + str(img_file) + '", '
                '"file_name": "corrupt.png", '
                '"file_url": "/file/corrupt.png"}'
            ),
        )
        session.add(file_row)
        session.add(job)
        await session.commit()

    from backend.core.image_ingest import ImageExtractionError

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=test_db()), \
         patch("backend.core.image_ingest.extract_text_from_image_bytes", side_effect=ImageExtractionError("Unreadable image matrix")):

        await execute_job(301)

    async with test_db() as session:
        j = await session.get(IngestionJob, 301)
        assert j.status == JobStatus.FAILED
        assert j.status != JobStatus.SUCCEEDED
        assert "Image extraction failed" in (j.last_error or "")

        f = await session.get(FileUpload, 301)
        assert f.status == ProcessingStatus.FAILED


@pytest.mark.asyncio
async def test_adversarial_audio_asr_empty_transcript_marks_failed(test_db, tmp_path, monkeypatch):
    """Stress test: Audio file yielding empty transcript marks job FAILED, never SUCCEEDED."""
    audio_file = tmp_path / "silent.mp3"
    audio_file.write_bytes(b"ID3silent")

    async with test_db() as session:
        file_row = FileUpload(
            id=302,
            filename="silent.mp3",
            original_filename="silent.mp3",
            file_path=str(audio_file),
            file_url="/file/silent.mp3",
            status=ProcessingStatus.PENDING,
            user_id=1,
        )
        job = IngestionJob(
            id=302,
            job_type="file",
            resource_id=302,
            user_id=1,
            user_email="adversary@test.com",
            status=JobStatus.RUNNING,
            attempts=3,
            max_attempts=3,
            payload=(
                '{"file_path": "' + str(audio_file) + '", '
                '"file_name": "silent.mp3", '
                '"file_url": "/file/silent.mp3"}'
            ),
        )
        session.add(file_row)
        session.add(job)
        await session.commit()

    monkeypatch.setattr(settings, "AUDIO_ASR_ENABLED", True)

    with patch("backend.worker.durable_jobs.async_session_maker", return_value=test_db()), \
         patch("backend.core.asr_client.transcribe_audio_bytes", new_callable=AsyncMock, return_value="   "):

        await execute_job(302)

    async with test_db() as session:
        j = await session.get(IngestionJob, 302)
        assert j.status == JobStatus.FAILED
        assert j.status != JobStatus.SUCCEEDED
        assert "ASR returned empty transcript" in (j.last_error or "")

        f = await session.get(FileUpload, 302)
        assert f.status == ProcessingStatus.FAILED


@pytest.mark.asyncio
async def test_adversarial_ocr_boundary_condition_chars(monkeypatch):
    """Verify exact character count boundary condition for OCR routing.
    - total_chars == 39 (< 40): MUST trigger OCR.
    - total_chars == 40 (>= 40): MUST skip OCR.
    """
    monkeypatch.setattr(settings, "OCR_MODE", "auto")
    monkeypatch.setattr(settings, "OCR_MIN_CHARS", 40)

    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 401
    m_job.user_email = "test@ocr.boundary"
    m_job.user_id = 1

    # Case A: 39 chars -> triggers OCR
    chunk_39 = MagicMock()
    chunk_39.text = "a" * 39
    payload_a = {"file_path": "boundary39.pdf", "file_name": "boundary39.pdf", "file_url": "/b39"}

    with patch("backend.parsers.parse_document", return_value=[chunk_39]), \
         patch("backend.core.pdf_render.render_pdf_pages", return_value=[b"png"]) as m_render, \
         patch("backend.core.ocr_client.ocr_image_bytes", new_callable=AsyncMock, return_value="ocr_text") as m_ocr, \
         patch("backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store") as m_add, \
         patch("backend.worker.durable_jobs._mark_resource_status"):

        await _execute_document(m_session, m_job, payload_a)
        m_render.assert_called_once()
        m_ocr.assert_called_once()
        if os.path.exists("boundary39.pdf.ocr.md"):
            os.remove("boundary39.pdf.ocr.md")

    # Case B: 40 chars -> skips OCR
    chunk_40 = MagicMock()
    chunk_40.text = "a" * 40
    payload_b = {"file_path": "boundary40.pdf", "file_name": "boundary40.pdf", "file_url": "/b40"}

    with patch("backend.parsers.parse_document", return_value=[chunk_40]), \
         patch("backend.core.pdf_render.render_pdf_pages") as m_render, \
         patch("backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store") as m_add, \
         patch("backend.worker.durable_jobs._mark_resource_status"):

        await _execute_document(m_session, m_job, payload_b)
        m_render.assert_not_called()
        m_add.assert_called_once_with("boundary40.pdf", "boundary40.pdf", "/b40", 401, "test@ocr.boundary", 1)

