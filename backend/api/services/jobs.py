"""Job-related domain service logic."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models import User, IngestionJob, JobStatus, ProcessingStatus
from backend.worker.durable_jobs import notify_workers, _mark_resource_status, get_job


async def retry_ingestion_job_service(session: AsyncSession, job: IngestionJob) -> Dict[str, Any]:
    """Reset attempts, clear errors, transition to PENDING and notify workers."""
    job.status = JobStatus.PENDING
    job.last_error = None
    job.attempts = 0
    job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await _mark_resource_status(session, job, ProcessingStatus.PENDING, None)
    await session.commit()
    await session.refresh(job)
    notify_workers()

    return {"status": job.status, "job_id": job.id}


async def get_job_service(
    session: AsyncSession,
    *,
    user: User,
    job_id: int,
) -> IngestionJob:
    """Fetch IngestionJob by ID, verifying user ownership; raise 404 if missing or unauthorized."""
    job = await get_job(session, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return job


async def retry_job_service(
    session: AsyncSession,
    *,
    user: User,
    job_id: int,
) -> Dict[str, Any]:
    """Validate status in (FAILED, CANCELLED), then perform retry."""
    job = await get_job_service(session, user=user, job_id=job_id)

    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry job in status '{job.status}'",
        )

    return await retry_ingestion_job_service(session, job)


async def list_jobs_service(
    session: AsyncSession,
    *,
    user_id: int,
    skip: int = 0,
    limit: int = 50,
) -> List[IngestionJob]:
    """Return paginated IngestionJob records for user_id."""
    limit = min(max(limit, 1), 100)
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.user_id == user_id)
        .order_by(desc(IngestionJob.id))
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())
