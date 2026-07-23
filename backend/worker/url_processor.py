import asyncio
import aiohttp
from bs4 import BeautifulSoup

from backend.api.models import Link, ProcessingStatus
from backend.vector_store.adapter import vector_db
from backend.core.logging import get_logger
from urllib.parse import urlparse
from backend.database import async_session_maker
from sqlalchemy import select
from backend.config import settings


vector_store = vector_db()
logger = get_logger()

# Legacy in-memory queue kept for backward compatibility; prefer durable_jobs.
url_processing_queue = asyncio.Queue()
concurrency_limit = asyncio.Semaphore(settings.LINKS_JOB_QUEUE_CONCURRENCY)


def get_base_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def process_url_queue():
    """Deprecated: durable job dispatcher handles link jobs. Drain legacy puts if any."""
    while True:
        try:
            link_id, url, user_email, headers = await url_processing_queue.get()
            logger.warning(
                "url_processing_queue is deprecated; processing legacy put via process_single_url"
            )
            asyncio.create_task(
                _legacy_safe_process(link_id, url, user_email, headers)
            )
        except Exception as e:
            logger.error(f"Error in URL processing queue: {str(e)}")
            await asyncio.sleep(1)


async def _legacy_safe_process(link_id, url, user_email, headers):
    try:
        await process_single_url(link_id, url, user_email, headers)
    except Exception as e:
        logger.error(f"legacy url process failed: {e}")


def extract_metadata_from_html(html_content, base_url):
    soup = BeautifulSoup(html_content, 'html.parser')

    text = soup.get_text()

    # Extract title
    title = soup.title.string if soup.title else None

    # Extract favicon
    favicon = None
    favicon_link = soup.find('link', rel=lambda r: r and (
        'icon' in r.lower() or 'shortcut icon' in r.lower()))
    if favicon_link and favicon_link.get('href'):
        favicon_url = favicon_link['href']
        # Handle relative URLs
        if favicon_url.startswith('/'):
            favicon = f"{base_url}{favicon_url}"
        else:
            favicon = favicon_url

    return title, favicon, text


async def process_single_url(link_id, url, user_email, headers, user_id=None):
    """
    Fetch link, embed content, update Link row.
    Raises on failure so durable job runner can retry.
    """
    async with concurrency_limit:
        logger.info(
            f"Processing URL {url} for user {user_email} (link ID: {link_id})")

        async with async_session_maker() as db:
            link = None
            try:
                stmt = select(Link).where(Link.id == link_id)
                result = await db.execute(stmt)
                link = result.scalars().first()

                if not link:
                    raise ValueError(f"Link with ID {link_id} not found")

                link.status = ProcessingStatus.IN_PROGRESS
                link.error_message = None
                await db.commit()

                async with aiohttp.ClientSession() as session:
                    request_kwargs = {
                        "timeout": 30,
                        "allow_redirects": True,
                        "max_redirects": 10,
                        "headers": headers or {},
                    }
                    async with session.get(url, **request_kwargs) as response:
                        if response.status != 200:
                            msg = f"HTTP {response.status}"
                            link.status = ProcessingStatus.FAILED
                            link.error_message = msg
                            await db.commit()
                            raise RuntimeError(
                                f"Failed to fetch URL {url}: {msg}")

                        html_content = await response.text()
                        base_url = get_base_url(str(response.url))
                        title, favicon, text_content = extract_metadata_from_html(
                            html_content, base_url)

                        link.title = title
                        link.favicon = favicon

                        await asyncio.to_thread(
                            vector_store.add_link_content_to_vector_store,
                            text_content, url, title, link_id, user_email, user_id)

                        link.status = ProcessingStatus.FINISHED
                        link.error_message = None
                        await db.commit()
                        logger.info(
                            f"Successfully processed URL {url} for user {user_email} and link_id={link_id}")

            except Exception as e:
                logger.error(
                    f"Error processing URL {url} for user {user_email}: {str(e)}")
                try:
                    if link is not None:
                        link.status = ProcessingStatus.FAILED
                        link.error_message = str(e)[:2000]
                        await db.commit()
                except Exception:
                    pass
                raise
