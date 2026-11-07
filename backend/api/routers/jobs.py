from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import current_active_user
from backend.api.models import User
from backend.api.schemas import JobResponse
from backend.api.services.jobs import (
    get_job_service,
    retry_job_service,
    list_jobs_service,
)
from backend.database import get_async_session

job_router = APIRouter(tags=["jobs"])


@job_router.get("/{job_id}", response_model=JobResponse, status_code=200)
async def get_ingestion_job(
    job_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    return await get_job_service(session, user=user, job_id=job_id)


@job_router.post("/{job_id}/retry", status_code=200)
async def retry_ingestion_job(
    job_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    return await retry_job_service(session, user=user, job_id=job_id)


@job_router.get("", response_model=list[JobResponse], status_code=200)
async def list_ingestion_jobs(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    return await list_jobs_service(session, user_id=user.id, skip=skip, limit=limit)
