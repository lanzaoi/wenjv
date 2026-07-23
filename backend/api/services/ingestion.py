"""Ingestion-related service helpers."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.worker.durable_jobs import (
    enqueue_document_job,
    enqueue_link_job,
)


async def queue_document(
    session: AsyncSession,
    *,
    source_type: str,
    resource_id: int,
    user_id: int,
    user_email: str,
    file_path: str,
    file_name: str,
    file_url: str,
):
    return await enqueue_document_job(
        session,
        source_type=source_type,
        resource_id=resource_id,
        user_id=user_id,
        user_email=user_email,
        file_path=file_path,
        file_name=file_name,
        file_url=file_url,
    )


async def queue_link(
    session: AsyncSession,
    *,
    link_id: int,
    url: str,
    user_id: int,
    user_email: str,
    headers: Optional[dict] = None,
):
    return await enqueue_link_job(
        session,
        link_id=link_id,
        url=url,
        user_id=user_id,
        user_email=user_email,
        headers=headers,
    )
