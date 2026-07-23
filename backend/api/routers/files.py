# backend/api/routers/files.py — files + notes
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy import select, desc, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
import os
import uuid

from backend.api.dependencies import current_active_user
from backend.core.utils import (
    save_file,
    update_file_with_backup,
    is_allowed_upload_filename,
    sanitize_upload_basename,
)
from backend.api.services.ingestion import queue_document
from backend.vector_store.adapter import vector_db
from backend.api.models import User, FileUpload, ProcessingStatus, Note
from backend.api.schemas import (
    FileUploadResponse,
    NoteCreateRequest,
    NoteCreateResponse,
    NoteList,
    NoteResponse,
    NoteUpdateRequest,
    NoteUpdateResponse,
    FilesList,
    FilePollingResponse,
    ResourceDeletedResponse,
    NoteBulkSyncResponse,
)
from backend.database import get_async_session
from backend.config import settings

vector_store = vector_db()
file_router = APIRouter(tags=["files"])

@file_router.post("/upload", response_model=FileUploadResponse, status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    original_name = file.filename or "upload.bin"
    if not is_allowed_upload_filename(original_name):
        allowed = ", ".join(settings.ALLOWED_UPLOAD_EXTENSIONS)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed extensions: {allowed}",
        )

    # Read with size cap (UploadFile may be spooled)
    max_bytes = settings.MAX_UPLOAD_BYTES
    chunk_size = 1024 * 1024
    total = 0
    chunks = []
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds max size of {max_bytes} bytes",
            )
        chunks.append(chunk)
    content = b"".join(chunks)

    safe_original = sanitize_upload_basename(original_name)
    # Generate a unique filename to prevent collisions
    unique_filename = f"{uuid.uuid4()}-{safe_original}"

    # Create the file path
    file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

    # Save the file
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
            user_id=user.id
        )
        session.add(db_note)
        await session.commit()
        await session.refresh(db_note)

        file_id = db_note.id
        created_at = db_note.created_at

    else:
        source_type = "file"

        file_url = f"/file/{unique_filename}"

        # Create a database entry
        db_file = FileUpload(
            filename=unique_filename,
            original_filename=original_name,
            file_path=str(file_path),
            file_url=file_url,
            status=ProcessingStatus.PENDING,
            error_message=None,
            content_type=file.content_type,
            user_id=user.id
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
    )
    # Return the file URL to the client
    return {
        "filename": unique_filename,
        "file_url": file_url,
        "status": ProcessingStatus.PENDING,
        "created_at": created_at
    }


# Files List endpoint
@file_router.get("/", response_model=FilesList, status_code=200)
async def list_uploaded_files(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    stmt = (
        select(FileUpload)
        .where(FileUpload.user_id == user.id)
        .order_by(desc(FileUpload.updated_at))
        .offset(skip)
        .limit(limit)
    )

    result = await session.execute(stmt)
    records = result.scalars().all()

    count_stmt = (
        select(func.count())
        .select_from(FileUpload)
        .where(FileUpload.user_id == user.id)
    )

    total_count = await session.execute(count_stmt)
    total_count = total_count.scalar() or 0

    result = [
        FileUploadResponse(
            file_url=record.file_url,
            filename=record.filename,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at
        ) for record in records
    ]
    # Return the file URL to the client
    return FilesList(
        files=result,
        total=total_count
    )


# Note upload endpoint
@file_router.post("/note", response_model=NoteCreateResponse, status_code=202)
async def create_note(
    note: NoteCreateRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    doc_id, file_path, filename, saved = save_file(note.content, note.title)

    if not saved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Error creating file"
        )

    file_url = f"/file/note/{filename}"

    # Create a database entry
    db_note = Note(
        url=file_url,
        title=note.title,
        filename=filename,
        file_path=str(file_path),
        status=ProcessingStatus.PENDING,
        user_id=user.id
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
        file_path=file_path,
        file_name=filename,
        file_url=file_url,
    )
    # Return the file URL to the client
    return NoteCreateResponse(
        id=db_note.id,
        url=file_url,
        title=note.title,
        status=db_note.status
    )


# Note List endpoint
@file_router.get("/note", response_model=NoteList, status_code=200)
async def list_notes(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    stmt = (
        select(Note)
        .where(Note.user_id == user.id)
        .order_by(desc(Note.updated_at))
        .offset(skip)
        .limit(limit)
    )

    result = await session.execute(stmt)
    records = result.scalars().all()

    count_stmt = (
        select(func.count())
        .select_from(Note)
        .where(Note.user_id == user.id)
    )

    total_count = await session.execute(count_stmt)
    total_count = total_count.scalar() or 0

    result = [
        NoteResponse(
            url=record.url,
            id=record.id,
            title=record.title,
            filename=record.filename,
            created_at=record.created_at,
            updated_at=record.updated_at
        ) for record in records
    ]
    # Return the file URL to the client
    return NoteList(
        notes=result,
        total=total_count
    )


@file_router.get("/note/{filename}")
async def get_note(
    filename: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    # Check if the file exists in the database
    result = await session.execute(
        select(Note).where(Note.filename == filename)
    )
    note_record = result.scalars().first()

    if not note_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Check if the user has access to the file
    if note_record.user_id != user.id and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this file"
        )

    # Check if the file exists on disk
    file_path = Path(note_record.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server"
        )

    # Return the file as a response
    return FileResponse(
        path=file_path,
        filename=note_record.title,
        media_type="text/markdown"
    )


@file_router.patch(
    "/note/{filename}",
    response_model=NoteUpdateResponse,
    status_code=200)
async def update_note(
    filename: str,
    note: NoteUpdateRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    result = await session.execute(
        select(Note)
        .where(Note.filename == filename, Note.user_id == user.id)
    )
    note_record = result.scalars().first()

    if not note_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    updated = update_file_with_backup(note.content, note_record.filename)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Error updating file"
        )

    note_record.status = ProcessingStatus.PENDING
    note_record.error_message = None
    await session.commit()

    # remove existing vector documents
    # and then add new set of updated documents
    vector_store.remove_documents(
        note_record.filename,
        user.email
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

    return NoteUpdateResponse(
        filename=note_record.filename,
        updated=True
    )

# re-sync all notes belonging to the user


@file_router.put(
    "/note/sync",
    response_model=NoteBulkSyncResponse,
    status_code=200)
async def sync_notes(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):

    await session.execute(
        update(Note)
        .where(Note.user_id == user.id)
        .values({"status": ProcessingStatus.PENDING})
    )

    result = await session.execute(
        select(Note)
        .where(Note.user_id == user.id)
    )
    note_records = result.scalars().all()

    for note in note_records:
        vector_store.remove_documents(
            note.filename,
            user.email
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

    return NoteBulkSyncResponse(
        count=len(note_records),
        updated=True
    )


@file_router.delete(
    "/note/{filename}",
    response_model=ResourceDeletedResponse,
    status_code=200)
async def delete_note(
    filename: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):

    result = await session.execute(
        select(Note)
        .where(Note.filename == filename, Note.user_id == user.id)
    )
    notes = result.scalars().all()

    if len(notes) == 1:
        note = notes[0]
        await session.execute(
            delete(Note).where(Note.id == note.id)
        )
        vector_store.remove_documents(
            note.filename,
            user.email
        )
        await session.commit()
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    return ResourceDeletedResponse(status="deleted")


@file_router.get(
    "/status/{filename}",
    response_model=FilePollingResponse,
    status_code=200)
async def get_file_status(
    filename: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    # Check if the file exists in the database
    result = await session.execute(
        select(FileUpload).where(
            FileUpload.filename == filename,
            FileUpload.user_id == user.id
        )
    )
    file_record = result.scalars().first()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    return FilePollingResponse(
        status=file_record.status,
        error_message=getattr(file_record, "error_message", None),
    )

@file_router.get("/{filename}")
async def get_file(
    filename: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    # Check if the file exists in the database
    result = await session.execute(
        select(FileUpload).where(FileUpload.filename == filename)
    )
    file_record = result.scalars().first()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Check if the user has access to the file
    if file_record.user_id != user.id and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this file"
        )

    # Check if the file exists on disk
    file_path = Path(file_record.file_path)
    if not file_path.exists():
        file_path = os.path.join(settings.UPLOAD_DIR, file_record.filename)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server"
        )

    # Return the file as a response
    return FileResponse(
        path=file_path,
        filename=file_record.original_filename,
        media_type=file_record.content_type
    )


@file_router.delete(
    "/{filename}",
    response_model=ResourceDeletedResponse,
    status_code=200)
async def delete_uploaded_file(
    filename: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):

    result = await session.execute(
        select(FileUpload)
        .where(FileUpload.filename == filename, FileUpload.user_id == user.id)
    )
    files = result.scalars().all()

    if len(files) == 1:
        fl = files[0]
        await session.execute(
            delete(FileUpload).where(FileUpload.id == fl.id)
        )
        vector_store.remove_documents(
            fl.filename,
            user.email
        )
        await session.commit()
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    return ResourceDeletedResponse(status="deleted")

