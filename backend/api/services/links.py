"""Link-related domain service logic."""
from __future__ import annotations

from typing import Optional, Tuple, List

from fastapi import HTTPException, status
from sqlalchemy import select, desc, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models import User, Link, ProcessingStatus
from backend.api.services.ingestion import queue_link
from backend.vector_store.adapter import vector_db
from backend.worker.url_processor_recursive import recursive_url_processing_queue

from backend.api.services.tags import tags_to_json, normalize_tags

vector_store = vector_db()


async def create_link_service(
    session: AsyncSession,
    *,
    user: User,
    url: str,
    headers: Optional[dict] = None,
    tags: Optional[List[str]] = None,
) -> Link:
    """Create a new Link record, enqueue ingestion job, commit and return Link."""
    cleaned_tags = normalize_tags(tags)
    db_link = Link(
        url=str(url),
        user_id=user.id,
        status=ProcessingStatus.PENDING,
        tags=tags_to_json(cleaned_tags),
    )
    session.add(db_link)
    await session.commit()
    await session.refresh(db_link)

    await queue_link(
        session,
        link_id=db_link.id,
        url=str(url),
        user_id=user.id,
        user_email=user.email,
        headers=dict(headers or {}),
        tags=cleaned_tags,
    )
    return db_link


async def create_links_bulk_service(
    session: AsyncSession,
    *,
    user: User,
    urls: list[str],
    headers: Optional[dict] = None,
) -> int:
    """Process a list of URLs, creating Link rows and queueing jobs; return successful count."""
    successful_count = 0
    headers_dict = dict(headers or {})

    for url in urls:
        try:
            db_link = Link(
                url=str(url),
                user_id=user.id,
                status=ProcessingStatus.PENDING,
            )
            session.add(db_link)
            await session.commit()
            await session.refresh(db_link)

            await queue_link(
                session,
                link_id=db_link.id,
                url=str(url),
                user_id=user.id,
                user_email=user.email,
                headers=headers_dict,
            )
            successful_count += 1
        except Exception:
            # Continue processing next URLs on error
            continue

    return successful_count


async def list_links_service(
    session: AsyncSession,
    *,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
) -> Tuple[List[Link], int]:
    """Return paginated Link records and total count for user_id."""
    stmt = (
        select(Link)
        .where(Link.user_id == user_id)
        .order_by(desc(Link.updated_at))
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    count_stmt = (
        select(func.count())
        .select_from(Link)
        .where(Link.user_id == user_id)
    )
    total_res = await session.execute(count_stmt)
    total_count = total_res.scalar() or 0

    return records, total_count


async def enqueue_recursive_crawl_service(
    *,
    user: User,
    url: str,
    headers: Optional[dict] = None,
) -> str:
    """Put crawl request onto the recursive crawler queue."""
    await recursive_url_processing_queue.put((str(url), user, headers))
    return str(url)


async def delete_link_service(
    session: AsyncSession,
    *,
    user: User,
    link_id: int,
) -> bool:
    """Delete Link record, remove vector embeddings, and commit."""
    result = await session.execute(
        select(Link).where(Link.id == link_id, Link.user_id == user.id)
    )
    links = result.scalars().all()
    if len(links) != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found",
        )

    link = links[0]
    await session.execute(
        delete(Link).where(Link.id == link.id)
    )
    vector_store.remove_link_documents(
        link.id,
        user.email,
    )
    await session.commit()
    return True
