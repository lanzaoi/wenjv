# backend/api/routers/links.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import current_active_user
from backend.api.models import User
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
from backend.api.services.links import (
    create_link_service,
    create_links_bulk_service,
    list_links_service,
    enqueue_recursive_crawl_service,
    delete_link_service,
)
from backend.database import get_async_session

link_router = APIRouter(tags=["links"])


@link_router.post("/submit", response_model=LinkResponse, status_code=202)
async def submit_link(
    link: LinkCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    db_link = await create_link_service(
        session,
        user=user,
        url=str(link.url),
        headers=link.headers,
        tags=link.tags,
    )
    return db_link


# Bulk Links submit end-point
@link_router.post("/bulk", response_model=BulkLinkResponse, status_code=202)
async def submit_links_bulk(
    links_data: BulkLinkCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    successful_count = await create_links_bulk_service(
        session,
        user=user,
        urls=links_data.urls,
        headers=links_data.headers,
    )
    return BulkLinkResponse(links_added=successful_count)


# Links List endpoint
@link_router.get("/", response_model=LinksList, status_code=200)
async def list_links(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    records, total_count = await list_links_service(
        session,
        user_id=user.id,
        skip=skip,
        limit=limit,
    )

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
    url = await enqueue_recursive_crawl_service(
        user=user,
        url=links_data.url,
        headers=links_data.headers,
    )
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
    await delete_link_service(session, user=user, link_id=id)
    return ResourceDeletedResponse(status="deleted")
