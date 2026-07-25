from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import current_active_user
from backend.api.models import User, IngestionJob, JobStatus
from backend.api.schemas import JobResponse
from backend.api.services.jobs import retry_ingestion_job_service
from backend.database import get_async_session
from backend.worker.durable_jobs import get_job

job_router = APIRouter(tags=["jobs"])


@job_router.get("/{job_id}", response_model=JobResponse, status_code=200)
async def get_ingestion_job(
    job_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    job = await get_job(session, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return job


@job_router.post("/{job_id}/retry", status_code=200)
async def retry_ingestion_job(
    job_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    job = await get_job(session, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry job in status '{job.status}'",
        )

    return await retry_ingestion_job_service(session, job)


@job_router.get("", response_model=list[JobResponse], status_code=200)
async def list_ingestion_jobs(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    limit = min(max(limit, 1), 100)
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.user_id == user.id)
        .order_by(desc(IngestionJob.id))
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())
