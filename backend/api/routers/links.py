# backend/api/routers/links.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import current_active_user
from backend.worker.url_processor_recursive import recursive_url_processing_queue
from backend.api.services.ingestion import queue_link
from backend.vector_store.adapter import vector_db
from backend.api.models import User, ProcessingStatus, Link
from backend.api.schemas import (
    LinkCreate,
    LinkResponse,
    BulkLinkCreate,
    BulkLinkResponse,
    LinkCrawl,
    LinkCrawlResponse,
    LinksList,
    ResourceDeletedResponse,
)
from backend.database import get_async_session

vector_store = vector_db()
link_router = APIRouter(tags=["links"])

@link_router.post("/submit", response_model=LinkResponse, status_code=202)
async def submit_link(
    link: LinkCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    db_link = Link(
        url=str(link.url),
        user_id=user.id,
        status=ProcessingStatus.PENDING
    )
    session.add(db_link)
    await session.commit()
    await session.refresh(db_link)

    # Durable job (survives restart)
    await queue_link(
        session,
        link_id=db_link.id,
        url=str(link.url),
        user_id=user.id,
        user_email=user.email,
        headers=dict(link.headers or {}),
    )

    return db_link


# Bulk Links submit end-point
@link_router.post("/bulk", response_model=BulkLinkResponse, status_code=202)
async def submit_links_bulk(
    links_data: BulkLinkCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    # Process each URL
    successful_links = []
    failed_urls = []

    for url in links_data.urls:
        try:
            # Create new link entry
            db_link = Link(
                url=str(url),
                user_id=user.id,
                status=ProcessingStatus.PENDING
            )
            session.add(db_link)
            await session.commit()
            await session.refresh(db_link)

            # Durable job (survives restart)
            await queue_link(
                session,
                link_id=db_link.id,
                url=str(url),
                user_id=user.id,
                user_email=user.email,
                headers=dict(links_data.headers or {}),
            )

            successful_links.append(db_link)
        except Exception as e:
            failed_urls.append(str(url))

    return BulkLinkResponse(links_added=len(successful_links))


# Links List endpoint
@link_router.get("/", response_model=LinksList, status_code=200)
async def list_links(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    stmt = (
        select(Link)
        .where(Link.user_id == user.id)
        .order_by(desc(Link.updated_at))
        .offset(skip)
        .limit(limit)
    )

    result = await session.execute(stmt)
    records = result.scalars().all()

    count_stmt = (
        select(func.count())
        .select_from(Link)
        .where(Link.user_id == user.id)
    )

    total_count = await session.execute(count_stmt)
    total_count = total_count.scalar() or 0

    result = [
        LinkResponse(
            url=record.url,
            id=record.id,
            title=record.title,
            favicon=record.favicon,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at
        ) for record in records
    ]
    # Return the file URL to the client
    return LinksList(
        links=result,
        total=total_count
    )


# Recursively Crawl the link
@link_router.post("/crawl", response_model=LinkCrawlResponse, status_code=202)
async def recursive_crawl(
    links_data: LinkCrawl,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):

    url = links_data.url
    await recursive_url_processing_queue.put((str(url), user, links_data.headers))

    return LinkCrawlResponse(status="submitted", url=url)


@link_router.delete(
    "/{id}",
    response_model=ResourceDeletedResponse,
    status_code=200)
async def delete_link(
    id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):

    result = await session.execute(
        select(Link)
        .where(Link.id == id, Link.user_id == user.id)
    )
    links = result.scalars().all()

    if len(links) == 1:
        link = links[0]
        await session.execute(
            delete(Link).where(Link.id == link.id)
        )
        vector_store.remove_link_documents(
            link.id,
            user.email
        )
        await session.commit()
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    return ResourceDeletedResponse(status="deleted")
