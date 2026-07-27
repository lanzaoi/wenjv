"""
Durable ingestion jobs backed by SQLite.

Flow:
  API enqueue_job() -> row status=pending -> notify wake
  dispatcher claims pending -> running -> execute
  success -> succeeded; failure -> retry pending or failed
  startup reclaim: stale running -> pending (if attempts left)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models import (
    FileUpload,
    IngestionJob,
    JobStatus,
    JobType,
    Link,
    Note,
    ProcessingStatus,
)
from backend.config import settings
from backend.core.logging import get_logger
from backend.database import async_session_maker
from backend.vector_store.adapter import vector_db

logger = get_logger()
vector_store = vector_db()

_wake = asyncio.Event()
_dispatcher_started = False


def notify_workers() -> None:
    _wake.set()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dumps(payload: dict) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


def _loads(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def enqueue_job(
    session: AsyncSession,
    *,
    job_type: str,
    resource_id: int,
    user_id: int,
    user_email: str,
    payload: Optional[dict] = None,
    max_attempts: Optional[int] = None,
) -> IngestionJob:
    job = IngestionJob(
        job_type=job_type,
        resource_id=resource_id,
        user_id=user_id,
        user_email=user_email,
        payload=_dumps(payload or {}),
        status=JobStatus.PENDING,
        attempts=0,
        max_attempts=max_attempts or settings.JOB_MAX_ATTEMPTS,
        last_error=None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    notify_workers()
    logger.info(
        f"enqueued job id={job.id} type={job_type} resource_id={resource_id}"
    )
    return job


async def enqueue_document_job(
    session: AsyncSession,
    *,
    source_type: str,
    resource_id: int,
    user_id: int,
    user_email: str,
    file_path: str,
    file_name: str,
    file_url: str,
) -> IngestionJob:
    job_type = JobType.NOTE if source_type == "note" else JobType.FILE
    return await enqueue_job(
        session,
        job_type=job_type,
        resource_id=resource_id,
        user_id=user_id,
        user_email=user_email,
        payload={
            "file_path": file_path,
            "file_name": file_name,
            "file_url": file_url,
            "source_type": source_type,
        },
    )


async def enqueue_link_job(
    session: AsyncSession,
    *,
    link_id: int,
    url: str,
    user_id: int,
    user_email: str,
    headers: Optional[dict] = None,
) -> IngestionJob:
    return await enqueue_job(
        session,
        job_type=JobType.LINK,
        resource_id=link_id,
        user_id=user_id,
        user_email=user_email,
        payload={"url": url, "headers": headers or {}},
    )


async def get_job(session: AsyncSession, job_id: int) -> Optional[IngestionJob]:
    result = await session.execute(
        select(IngestionJob).where(IngestionJob.id == job_id)
    )
    return result.scalars().first()


async def reclaim_stale_jobs(session: AsyncSession) -> int:
    """Turn stuck running jobs back to pending (or failed if out of attempts)."""
    cutoff = _utcnow() - timedelta(seconds=settings.JOB_STALE_SECONDS)
    result = await session.execute(
        select(IngestionJob).where(
            IngestionJob.status == JobStatus.RUNNING,
            or_(
                IngestionJob.started_at.is_(None),
                IngestionJob.started_at < cutoff,
            ),
        )
    )
    jobs = list(result.scalars().all())
    n = 0
    for job in jobs:
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.last_error = (job.last_error or "")[:1800] + " | stale timeout"
            job.finished_at = _utcnow()
            await _mark_resource_failed(
                session, job, job.last_error or "stale timeout"
            )
        else:
            job.status = JobStatus.PENDING
            job.started_at = None
        job.updated_at = _utcnow()
        n += 1
    if n:
        await session.commit()
        logger.warning(f"reclaimed {n} stale ingestion job(s)")
        notify_workers()
    return n


async def claim_next_job(session: AsyncSession) -> Optional[IngestionJob]:
    """Claim one pending job (SQLite-friendly: select then update)."""
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.status == JobStatus.PENDING)
        .order_by(IngestionJob.id.asc())
        .limit(1)
    )
    job = result.scalars().first()
    if not job:
        return None

    job.status = JobStatus.RUNNING
    job.attempts = int(job.attempts or 0) + 1
    job.started_at = _utcnow()
    job.updated_at = _utcnow()
    job.last_error = None
    await session.commit()
    await session.refresh(job)
    return job


async def _load_resource(session: AsyncSession, job: IngestionJob):
    if job.job_type == JobType.NOTE:
        stmt = select(Note).where(Note.id == job.resource_id)
    elif job.job_type == JobType.FILE:
        stmt = select(FileUpload).where(FileUpload.id == job.resource_id)
    elif job.job_type == JobType.LINK:
        stmt = select(Link).where(Link.id == job.resource_id)
    else:
        return None
    result = await session.execute(stmt)
    return result.scalars().first()


async def _mark_resource_status(
    session: AsyncSession,
    job: IngestionJob,
    status: str,
    error_message: Optional[str] = None,
):
    row = await _load_resource(session, job)
    if not row:
        return
    row.status = status
    if hasattr(row, "error_message"):
        row.error_message = error_message
    from sqlalchemy import func as sa_func

    if hasattr(row, "updated_at"):
        row.updated_at = sa_func.now()


async def _mark_resource_failed(session: AsyncSession, job: IngestionJob, err: str):
    await _mark_resource_status(
        session, job, ProcessingStatus.FAILED, err[:2000]
    )


async def _execute_document(session: AsyncSession, job: IngestionJob, payload: dict):
    file_path = payload.get("file_path")
    file_name = payload.get("file_name")
    file_url = payload.get("file_url")
    if not file_path or not file_name:
        raise ValueError("document job missing file_path/file_name")

    await _mark_resource_status(session, job, ProcessingStatus.IN_PROGRESS, None)
    await session.commit()

    from backend.parsers import parse_document
    from backend.config import settings
    from backend.core.ocr_client import ocr_image_bytes
    from backend.core.pdf_render import render_pdf_pages
    import os

    # 1. Parse document first
    parsed = await asyncio.to_thread(parse_document, file_path)
    total_chars = sum(len(c.text or "") for c in parsed)
    
    # 2. Check if OCR is needed
    ocr_mode = getattr(settings, "OCR_MODE", "off")
    need_ocr = False
    
    if ocr_mode == "always":
        need_ocr = True
    elif ocr_mode == "auto":
        ocr_min_chars = getattr(settings, "OCR_MIN_CHARS", 40)
        if total_chars < ocr_min_chars:
            need_ocr = True

    # 3. Apply OCR if needed and it's a PDF
    if need_ocr and file_name.lower().endswith(".pdf"):
        try:
            max_pages = getattr(settings, "OCR_MAX_PAGES", 30)
            png_bytes_list = await asyncio.to_thread(render_pdf_pages, file_path, max_pages)
            
            ocr_texts = []
            for png in png_bytes_list:
                text = await ocr_image_bytes(png)
                if text:
                    ocr_texts.append(text)
                    
            if ocr_texts:
                combined_ocr = "\n\n".join(ocr_texts)
                original_text = "\n\n".join((c.text or "") for c in parsed)
                final_text = original_text + "\n\n---\n\n" + combined_ocr
                
                # Write to a temporary markdown file to avoid re-parsing as PDF
                temp_file = file_path + ".ocr.md"
                def _write_temp():
                    with open(temp_file, "w", encoding="utf-8") as f:
                        f.write(final_text)
                await asyncio.to_thread(_write_temp)
                
                # Redirect file_path so load_and_chunk_document treats it as markdown
                file_path = temp_file
                
        except Exception as e:
            logger.error(f"OCR failed for {file_name}: {e}")
            await _mark_resource_failed(session, job, f"OCR extraction failed: {str(e)}")
            return

    # 4. Finally pass to vector store
    await asyncio.to_thread(
        vector_store.add_uploaded_document_content_to_vector_store,
        file_path,
        file_name,
        file_url,
        job.resource_id,
        job.user_email,
        job.user_id,
    )

    if file_name.lower().endswith(".pdf") and settings.MULTIMODAL_ENABLED:
        try:
            from backend.core.multimodal import process_pdf_images, process_pdf_tables
            img_docs = await process_pdf_images(file_path, str(job.resource_id))
            tbl_docs = await process_pdf_tables(file_path, str(job.resource_id))
            all_mm_docs = img_docs + tbl_docs
            if all_mm_docs:
                for doc in all_mm_docs:
                    doc.metadata.update({
                        "source": file_url,
                        "filename": file_name,
                        "belongs_to": job.user_email,
                        "user_id": str(job.user_id) if job.user_id is not None else None,
                        "file_id": str(job.resource_id),
                        "resource_id": str(job.resource_id),
                    })
                await asyncio.to_thread(vector_store.add_documents, all_mm_docs)
        except Exception as mm_err:
            logger.warning(f"Multimodal ingestion failed for {file_name} (fail-open): {mm_err}")

    await _mark_resource_status(session, job, ProcessingStatus.FINISHED, None)


async def _execute_link(session: AsyncSession, job: IngestionJob, payload: dict):
    # Lazy import to avoid circular imports at module load
    from backend.worker.url_processor import process_single_url

    url = payload.get("url")
    headers = payload.get("headers") or {}
    if not url:
        raise ValueError("link job missing url")

    await process_single_url(
        job.resource_id, url, job.user_email, headers, user_id=job.user_id
    )


async def execute_job(job_id: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(IngestionJob).where(IngestionJob.id == job_id)
        )
        job = result.scalars().first()
        if not job:
            logger.error(f"job {job_id} not found")
            return
        if job.status != JobStatus.RUNNING:
            # lost race / already finished
            return

        payload = _loads(job.payload)
        try:
            if job.job_type in (JobType.FILE, JobType.NOTE, "file", "note"):
                await _execute_document(session, job, payload)
            elif job.job_type in (JobType.LINK, "link"):
                await _execute_link(session, job, payload)
            else:
                raise ValueError(f"unknown job_type={job.job_type}")

            job.status = JobStatus.SUCCEEDED
            job.finished_at = _utcnow()
            job.updated_at = _utcnow()
            job.last_error = None
            await session.commit()
            logger.info(f"job {job_id} succeeded type={job.job_type}")
        except Exception as e:
            err = str(e)[:2000]
            logger.error(f"job {job_id} failed: {err}")
            job.last_error = err
            job.updated_at = _utcnow()

            if job.attempts < job.max_attempts:
                job.status = JobStatus.PENDING
                job.started_at = None
                # leave resource as pending/in_progress so UI can retry wait
                await _mark_resource_status(
                    session, job, ProcessingStatus.PENDING, err
                )
                await session.commit()
                notify_workers()
                logger.info(
                    f"job {job_id} re-queued attempt={job.attempts}/{job.max_attempts}"
                )
            else:
                job.status = JobStatus.FAILED
                job.finished_at = _utcnow()
                await _mark_resource_failed(session, job, err)
                await session.commit()
                logger.error(f"job {job_id} permanently failed")


async def job_dispatcher_loop() -> None:
    """Single dispatcher: claim pending jobs and run under concurrency limit."""
    global _dispatcher_started
    if _dispatcher_started:
        return
    _dispatcher_started = True

    max_c = max(1, int(settings.JOB_WORKER_CONCURRENCY))
    in_flight = 0
    lock = asyncio.Lock()
    logger.info(f"ingestion job dispatcher started concurrency={max_c}")

    async def _run(job_id: int):
        nonlocal in_flight
        try:
            await execute_job(job_id)
        finally:
            async with lock:
                in_flight -= 1
            notify_workers()

    while True:
        try:
            async with async_session_maker() as session:
                await reclaim_stale_jobs(session)

            claimed_any = False
            while True:
                async with lock:
                    if in_flight >= max_c:
                        break
                async with async_session_maker() as session:
                    job = await claim_next_job(session)
                if not job:
                    break
                async with lock:
                    in_flight += 1
                claimed_any = True
                asyncio.create_task(_run(job.id))

            if not claimed_any:
                _wake.clear()
                try:
                    await asyncio.wait_for(
                        _wake.wait(),
                        timeout=settings.JOB_POLL_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"job dispatcher error: {e}")
            await asyncio.sleep(1)


async def start_job_workers() -> None:
    """Idempotent startup hook for FastAPI."""
    async with async_session_maker() as session:
        await reclaim_stale_jobs(session)
        # also reset any plain pending resources wake
        result = await session.execute(
            select(IngestionJob.id)
            .where(IngestionJob.status == JobStatus.PENDING)
            .limit(1)
        )
        if result.first():
            notify_workers()
    asyncio.create_task(job_dispatcher_loop())
