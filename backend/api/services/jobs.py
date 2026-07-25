"""Job-related service helpers."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models import IngestionJob, JobStatus, ProcessingStatus
from backend.worker.durable_jobs import notify_workers, _mark_resource_status


async def retry_ingestion_job_service(session: AsyncSession, job: IngestionJob) -> Dict[str, Any]:
    job.status = JobStatus.PENDING
    job.last_error = None
    job.attempts = 0
    job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    await _mark_resource_status(session, job, ProcessingStatus.PENDING, None)
    await session.commit()
    await session.refresh(job)
    notify_workers()
    
    return {"status": job.status, "job_id": job.id}
