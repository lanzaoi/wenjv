"""
Tags management and retrieval mapping service for wenjv.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple, Union

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.api.models import FileUpload, Link, Note
from backend.config import settings
from backend.database import QueryResultCacheTable, sync_engine

logger = logging.getLogger(settings.LOGGER_NAME)

MAX_TAGS_PER_RESOURCE = 8
MAX_TAG_LENGTH = 24


def normalize_tags(raw_tags: Union[List[str], str, None]) -> List[str]:
    """Normalize tags: strip whitespace, remove leading '#', lowercase ASCII, deduplicate."""
    if not raw_tags:
        return []

    items: List[str] = []
    if isinstance(raw_tags, str):
        # Try JSON parse first
        raw_str = raw_tags.strip()
        if raw_str.startswith("[") and raw_str.endswith("]"):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, list):
                    items = [str(x) for x in parsed]
            except Exception:
                items = [raw_str]
        elif "," in raw_str:
            items = raw_str.split(",")
        elif " " in raw_str:
            items = raw_str.split()
        else:
            items = [raw_str]
    elif isinstance(raw_tags, (list, tuple, set)):
        items = [str(x) for x in raw_tags]

    seen: Set[str] = set()
    cleaned: List[str] = []
    for item in items:
        # Strip whitespace and surrounding '#'
        t = item.strip().strip("#").strip()
        if not t:
            continue
        # Lowercase ascii while preserving unicode/Chinese
        t = t.lower()
        if len(t) > MAX_TAG_LENGTH:
            t = t[:MAX_TAG_LENGTH]
        if t not in seen:
            seen.add(t)
            cleaned.append(t)
        if len(cleaned) >= MAX_TAGS_PER_RESOURCE:
            break

    return cleaned


def tags_to_json(tags: Union[List[str], str, None]) -> str:
    """Normalize tags and serialize to JSON array string."""
    return json.dumps(normalize_tags(tags), ensure_ascii=False)


def tags_from_json(raw_json: Optional[str]) -> List[str]:
    """Deserialize JSON array string to normalized list of tags."""
    if not raw_json:
        return []
    try:
        data = json.loads(raw_json)
        if isinstance(data, list):
            return normalize_tags(data)
    except Exception:
        pass
    return []


async def get_user_tags_summary(session: AsyncSession, user_id: int, limit: int = 50) -> List[Dict[str, Union[str, int]]]:
    """Return top tags and their counts for a user."""
    counts: Counter[str] = Counter()

    # Query file_uploads
    f_res = await session.execute(
        select(FileUpload.tags).where(FileUpload.user_id == user_id)
    )
    for (t_str,) in f_res:
        counts.update(tags_from_json(t_str))

    # Query notes
    n_res = await session.execute(
        select(Note.tags).where(Note.user_id == user_id)
    )
    for (t_str,) in n_res:
        counts.update(tags_from_json(t_str))

    # Query links
    l_res = await session.execute(
        select(Link.tags).where(Link.user_id == user_id)
    )
    for (t_str,) in l_res:
        counts.update(tags_from_json(t_str))

    sorted_tags = [
        {"name": name, "count": count}
        for name, count in counts.most_common(limit)
    ]
    return sorted_tags


def get_user_tags_summary_sync(user_id: int, limit: int = 50) -> List[Dict[str, Union[str, int]]]:
    """Synchronous helper for auto-tagger vocabulary injection."""
    counts: Counter[str] = Counter()
    try:
        with Session(sync_engine) as session:
            for (t_str,) in session.query(FileUpload.tags).filter(FileUpload.user_id == user_id).all():
                counts.update(tags_from_json(t_str))
            for (t_str,) in session.query(Note.tags).filter(Note.user_id == user_id).all():
                counts.update(tags_from_json(t_str))
            for (t_str,) in session.query(Link.tags).filter(Link.user_id == user_id).all():
                counts.update(tags_from_json(t_str))
    except Exception as e:
        logger.warning(f"Error fetching user tag vocabulary: {e}")

    return [{"name": name, "count": count} for name, count in counts.most_common(limit)]


async def update_resource_tags(
    session: AsyncSession,
    user_id: int,
    source_type: str,
    resource_id: int,
    raw_tags: Union[List[str], str, None],
) -> Optional[List[str]]:
    """Update tags for a file, note, or link, and invalidate user query cache."""
    cleaned = normalize_tags(raw_tags)
    json_str = json.dumps(cleaned, ensure_ascii=False)

    st = source_type.lower()
    entity = None
    if st == "file":
        res = await session.execute(
            select(FileUpload).where(FileUpload.id == resource_id, FileUpload.user_id == user_id)
        )
        entity = res.scalar_one_or_none()
    elif st == "note":
        res = await session.execute(
            select(Note).where(Note.id == resource_id, Note.user_id == user_id)
        )
        entity = res.scalar_one_or_none()
    elif st == "link":
        res = await session.execute(
            select(Link).where(Link.id == resource_id, Link.user_id == user_id)
        )
        entity = res.scalar_one_or_none()

    if not entity:
        return None

    entity.tags = json_str
    await session.commit()
    await session.refresh(entity)

    # Invalidate search cache for this user (both cache.db and main session)
    try:
        from backend.database import get_cache_engine
        from sqlalchemy.orm import Session
        with Session(get_cache_engine()) as cache_sess:
            cache_sess.execute(
                delete(QueryResultCacheTable).where(QueryResultCacheTable.user_id == user_id)
            )
            cache_sess.commit()
    except Exception as e:
        logger.debug(f"Cache engine invalidation note: {e}")

    try:
        await session.execute(
            delete(QueryResultCacheTable).where(QueryResultCacheTable.user_id == user_id)
        )
        await session.commit()
    except Exception as e:
        logger.warning(f"Failed to invalidate query cache after tag update: {e}")

    return cleaned


def resolve_sources_by_tags(
    user_id: int,
    query_tags: List[str],
) -> Tuple[Dict[str, int], List[int], List[str]]:
    """
    Resolve matching resource source identifiers and resource_ids from SQLite by tags.
    Returns:
        (source_tag_counts, matched_resource_ids, all_include_sources)
    """
    cleaned_query_tags = set(normalize_tags(query_tags))
    if not cleaned_query_tags or user_id is None:
        return {}, [], []

    source_tag_counts: Dict[str, int] = {}
    matched_resource_ids: List[int] = []
    all_sources: List[str] = []

    try:
        with Session(sync_engine) as session:
            # Check Notes
            notes = session.query(Note).filter(Note.user_id == user_id).all()
            for n in notes:
                n_tags = set(tags_from_json(n.tags))
                overlap = len(n_tags & cleaned_query_tags)
                if overlap > 0:
                    matched_resource_ids.append(n.id)
                    # Identifiers used as "source" in LanceDB/FTS5
                    sources = [s for s in [n.filename, n.file_path, n.url, n.title] if s]
                    for s in sources:
                        source_tag_counts[s] = max(source_tag_counts.get(s, 0), overlap)
                        if s not in all_sources:
                            all_sources.append(s)

            # Check Files
            files = session.query(FileUpload).filter(FileUpload.user_id == user_id).all()
            for f in files:
                f_tags = set(tags_from_json(f.tags))
                overlap = len(f_tags & cleaned_query_tags)
                if overlap > 0:
                    matched_resource_ids.append(f.id)
                    sources = [s for s in [f.filename, f.file_path, f.original_filename, f.file_url] if s]
                    for s in sources:
                        source_tag_counts[s] = max(source_tag_counts.get(s, 0), overlap)
                        if s not in all_sources:
                            all_sources.append(s)

            # Check Links
            links = session.query(Link).filter(Link.user_id == user_id).all()
            for l in links:
                l_tags = set(tags_from_json(l.tags))
                overlap = len(l_tags & cleaned_query_tags)
                if overlap > 0:
                    matched_resource_ids.append(l.id)
                    sources = [s for s in [l.url, l.title] if s]
                    for s in sources:
                        source_tag_counts[s] = max(source_tag_counts.get(s, 0), overlap)
                        if s not in all_sources:
                            all_sources.append(s)

    except Exception as e:
        logger.error(f"Error resolving sources by tags: {e}")

    return source_tag_counts, matched_resource_ids, all_sources


async def backfill_user_tags(session: AsyncSession, user_id: int) -> int:
    """Find all untagged resources for user and populate auto-tags."""
    from backend.core.auto_tagger import generate_document_tags
    import os

    count = 0

    # Backfill notes
    n_res = await session.execute(
        select(Note).where(Note.user_id == user_id)
    )
    for note in n_res.scalars().all():
        existing = tags_from_json(note.tags)
        if not existing:
            try:
                sample = ""
                if note.file_path and os.path.exists(note.file_path):
                    try:
                        with open(note.file_path, "r", encoding="utf-8", errors="ignore") as fp:
                            sample = fp.read(1500)
                    except Exception:
                        pass
                tags = await generate_document_tags(
                    text=sample,
                    title=note.title or note.filename,
                    user_id=user_id,
                )
                note.tags = tags_to_json(tags)
                count += 1
            except Exception as e:
                logger.warning(f"Backfill note {note.id} tag failed: {e}")

    # Backfill files
    f_res = await session.execute(
        select(FileUpload).where(FileUpload.user_id == user_id)
    )
    for f in f_res.scalars().all():
        existing = tags_from_json(f.tags)
        if not existing:
            try:
                sample = ""
                if f.file_path and os.path.exists(f.file_path):
                    try:
                        with open(f.file_path, "r", encoding="utf-8", errors="ignore") as fp:
                            sample = fp.read(1500)
                    except Exception:
                        pass
                tags = await generate_document_tags(
                    text=sample,
                    title=f.original_filename or f.filename,
                    user_id=user_id,
                )
                f.tags = tags_to_json(tags)
                count += 1
            except Exception as e:
                logger.warning(f"Backfill file {f.id} tag failed: {e}")

    # Backfill links
    l_res = await session.execute(
        select(Link).where(Link.user_id == user_id)
    )
    for l in l_res.scalars().all():
        existing = tags_from_json(l.tags)
        if not existing:
            try:
                tags = await generate_document_tags(
                    text=l.url or "",
                    title=l.title or l.url,
                    user_id=user_id,
                )
                l.tags = tags_to_json(tags)
                count += 1
            except Exception as e:
                logger.warning(f"Backfill link {l.id} tag failed: {e}")

    await session.commit()
    return count
