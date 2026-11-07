"""File-related domain service logic."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple, List
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, desc, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models import User, FileUpload, Note, ProcessingStatus
from backend.api.services.ingestion import queue_document
from backend.config import settings
from backend.core.utils import sanitize_upload_basename
from backend.vector_store.adapter import vector_db

from backend.api.services.tags import tags_to_json, normalize_tags

vector_store = vector_db()


async def upload_file_service(
    session: AsyncSession,
    *,
    user: User,
    original_name: str,
    content: bytes,
    content_type: Optional[str] = None,
    initial_tags: Optional[List[str]] = None,
) -> dict:
    """Handle physical disk saving, DB entity creation, and ingestion queueing for uploaded files."""
    safe_original = sanitize_upload_basename(original_name)
    unique_filename = f"{uuid.uuid4()}-{safe_original}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)
    cleaned_tags = normalize_tags(initial_tags)

    with open(file_path, "wb") as buffer:
        buffer.write(content)

    if safe_original.lower().endswith(".md") or safe_original.lower().endswith(".markdown"):
        source_type = "note"
        file_url = f"/file/note/{unique_filename}"

        db_note = Note(
            url=file_url,
            title=original_name,
            filename=unique_filename,
            file_path=str(file_path),
            status=ProcessingStatus.PENDING,
            error_message=None,
            tags=tags_to_json(cleaned_tags),
            user_id=user.id,
        )
        session.add(db_note)
        await session.commit()
        await session.refresh(db_note)

        file_id = db_note.id
        created_at = db_note.created_at
    else:
        source_type = "file"
        file_url = f"/file/{unique_filename}"

        db_file = FileUpload(
            filename=unique_filename,
            original_filename=original_name,
            file_path=str(file_path),
            file_url=file_url,
            status=ProcessingStatus.PENDING,
            error_message=None,
            content_type=content_type,
            tags=tags_to_json(cleaned_tags),
            user_id=user.id,
        )
        session.add(db_file)
        await session.commit()
        await session.refresh(db_file)

        file_id = db_file.id
        created_at = db_file.created_at

    await queue_document(
        session,
        source_type=source_type,
        resource_id=file_id,
        user_id=user.id,
        user_email=user.email,
        file_path=file_path,
        file_name=unique_filename,
        file_url=file_url,
        tags=cleaned_tags,
    )

    return {
        "id": file_id,
        "filename": unique_filename,
        "file_url": file_url,
        "status": ProcessingStatus.PENDING,
        "tags": cleaned_tags,
        "created_at": created_at,
    }


async def list_files_service(
    session: AsyncSession,
    *,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
) -> Tuple[List[FileUpload], int]:
    """Return paginated FileUpload records and total count for user_id."""
    stmt = (
        select(FileUpload)
        .where(FileUpload.user_id == user_id)
        .order_by(desc(FileUpload.updated_at))
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    count_stmt = (
        select(func.count())
        .select_from(FileUpload)
        .where(FileUpload.user_id == user_id)
    )
    total_res = await session.execute(count_stmt)
    total_count = total_res.scalar() or 0

    return records, total_count


async def get_file_status_service(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
) -> FileUpload:
    """Fetch FileUpload record owned by user; raise 404 if not found."""
    result = await session.execute(
        select(FileUpload).where(
            FileUpload.filename == filename,
            FileUpload.user_id == user.id,
        )
    )
    file_record = result.scalars().first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    return file_record


async def get_file_for_download_service(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
) -> Tuple[Path, str, Optional[str]]:
    """Return (file_path, original_filename, content_type) verifying ownership and disk existence."""
    result = await session.execute(
        select(FileUpload).where(FileUpload.filename == filename)
    )
    file_record = result.scalars().first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    if file_record.user_id != user.id and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this file",
        )

    file_path = Path(file_record.file_path)
    if not file_path.exists():
        file_path = Path(os.path.join(settings.UPLOAD_DIR, file_record.filename))
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server",
        )

    return file_path, file_record.original_filename, file_record.content_type


async def delete_file_service(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
) -> bool:
    """Delete FileUpload record, remove vector embeddings, and commit."""
    result = await session.execute(
        select(FileUpload).where(
            FileUpload.filename == filename,
            FileUpload.user_id == user.id,
        )
    )
    files = result.scalars().all()
    if len(files) != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    fl = files[0]
    await session.execute(
        delete(FileUpload).where(FileUpload.id == fl.id)
    )
    vector_store.remove_documents(fl.filename, user.email)
    await session.commit()
    return True
