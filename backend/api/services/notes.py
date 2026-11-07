"""Note-related domain service logic."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, List

from fastapi import HTTPException, status
from sqlalchemy import select, desc, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models import User, Note, ProcessingStatus
from backend.api.services.ingestion import queue_document
from backend.core.utils import save_file, update_file_with_backup
from backend.api.services.files import vector_store


from backend.api.services.tags import tags_to_json, normalize_tags


async def create_note_service(
    session: AsyncSession,
    *,
    user: User,
    title: str,
    content: str,
    tags: Optional[List[str]] = None,
) -> Note:
    """Save content to disk, create Note record, enqueue ingestion job, commit, return Note."""
    doc_id, file_path, filename, saved = save_file(content, title)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Error creating file",
        )

    file_url = f"/file/note/{filename}"
    cleaned_tags = normalize_tags(tags)
    db_note = Note(
        url=file_url,
        title=title,
        filename=filename,
        file_path=str(file_path),
        status=ProcessingStatus.PENDING,
        tags=tags_to_json(cleaned_tags),
        user_id=user.id,
    )
    session.add(db_note)
    await session.commit()
    await session.refresh(db_note)

    await queue_document(
        session,
        source_type="note",
        resource_id=db_note.id,
        user_id=user.id,
        user_email=user.email,
        file_path=str(file_path),
        file_name=filename,
        file_url=file_url,
        tags=cleaned_tags,
    )
    return db_note


async def list_notes_service(
    session: AsyncSession,
    *,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
) -> Tuple[List[Note], int]:
    """Return paginated Note records and total count for user_id."""
    stmt = (
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(desc(Note.updated_at))
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    count_stmt = (
        select(func.count())
        .select_from(Note)
        .where(Note.user_id == user_id)
    )
    total_res = await session.execute(count_stmt)
    total_count = total_res.scalar() or 0

    return records, total_count


async def get_note_for_download_service(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
) -> Tuple[Path, str]:
    """Return (file_path, note.title) validating user access and disk file existence."""
    result = await session.execute(
        select(Note).where(Note.filename == filename)
    )
    note_record = result.scalars().first()
    if not note_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    if note_record.user_id != user.id and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this file",
        )

    file_path = Path(note_record.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server",
        )

    return file_path, note_record.title


async def update_note_service(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
    content: str,
) -> Note:
    """Update file on disk with backup, set status PENDING, remove old vector docs, and re-enqueue."""
    result = await session.execute(
        select(Note).where(Note.filename == filename, Note.user_id == user.id)
    )
    note_record = result.scalars().first()
    if not note_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    updated = update_file_with_backup(content, note_record.filename)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Error updating file",
        )

    note_record.status = ProcessingStatus.PENDING
    note_record.error_message = None
    await session.commit()

    vector_store.remove_documents(
        note_record.filename,
        user.email,
    )

    await queue_document(
        session,
        source_type="note",
        resource_id=note_record.id,
        user_id=user.id,
        user_email=user.email,
        file_path=note_record.file_path,
        file_name=note_record.filename,
        file_url=note_record.url,
    )

    return note_record


async def sync_user_notes_service(
    session: AsyncSession,
    *,
    user: User,
) -> int:
    """Bulk reset user notes to PENDING, purge vector documents, re-enqueue each note."""
    await session.execute(
        update(Note)
        .where(Note.user_id == user.id)
        .values({"status": ProcessingStatus.PENDING})
    )

    result = await session.execute(
        select(Note).where(Note.user_id == user.id)
    )
    note_records = list(result.scalars().all())

    for note in note_records:
        vector_store.remove_documents(
            note.filename,
            user.email,
        )

    for note_record in note_records:
        await queue_document(
            session,
            source_type="note",
            resource_id=note_record.id,
            user_id=user.id,
            user_email=user.email,
            file_path=note_record.file_path,
            file_name=note_record.filename,
            file_url=note_record.url,
        )

    return len(note_records)


async def delete_note_service(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
) -> bool:
    """Delete Note record, remove vector embeddings, and commit."""
    result = await session.execute(
        select(Note).where(Note.filename == filename, Note.user_id == user.id)
    )
    notes = result.scalars().all()
    if len(notes) != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    note = notes[0]
    await session.execute(
        delete(Note).where(Note.id == note.id)
    )
    vector_store.remove_documents(
        note.filename,
        user.email,
    )
    await session.commit()
    return True
