# backend/api/routers/files.py — files + notes
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import current_active_user
from backend.core.utils import is_allowed_upload_filename
from backend.api.models import User
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
from backend.api.services.files import (
    upload_file_service,
    list_files_service,
    get_file_status_service,
    get_file_for_download_service,
    delete_file_service,
)
from backend.api.services.notes import (
    create_note_service,
    list_notes_service,
    get_note_for_download_service,
    update_note_service,
    sync_user_notes_service,
    delete_note_service,
)
from backend.database import get_async_session
from backend.config import settings

file_router = APIRouter(tags=["files"])


@file_router.post("/upload", response_model=FileUploadResponse, status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    tags: Optional[str] = Form(None),
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
        
    image_exts = {".png", ".jpg", ".jpeg"}
    lower_name = original_name.lower()
    if any(lower_name.endswith(e) for e in image_exts):
        from backend.core.image_ingest_gate import image_ingest_allowed
        allowed, reason = image_ingest_allowed(settings)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image upload disabled or no extraction backend available: {reason}",
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

    result = await upload_file_service(
        session,
        user=user,
        original_name=original_name,
        content=content,
        content_type=file.content_type,
        initial_tags=tags,
    )
    return result


# Files List endpoint
@file_router.get("/", response_model=FilesList, status_code=200)
async def list_uploaded_files(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    records, total_count = await list_files_service(
        session,
        user_id=user.id,
        skip=skip,
        limit=limit,
    )

    result = [
        FileUploadResponse(
            id=record.id,
            file_url=record.file_url,
            filename=record.filename,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            tags=record.tags or "[]",
        ) for record in records
    ]
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
    db_note = await create_note_service(
        session,
        user=user,
        title=note.title,
        content=note.content,
        tags=note.tags,
    )
    return NoteCreateResponse(
        id=db_note.id,
        url=db_note.url,
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
    records, total_count = await list_notes_service(
        session,
        user_id=user.id,
        skip=skip,
        limit=limit,
    )

    result = [
        NoteResponse(
            url=record.url,
            id=record.id,
            title=record.title,
            filename=record.filename,
            created_at=record.created_at,
            updated_at=record.updated_at or record.created_at,
            tags=record.tags or "[]",
        ) for record in records
    ]
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
    file_path, title = await get_note_for_download_service(
        session,
        user=user,
        filename=filename,
    )
    return FileResponse(
        path=file_path,
        filename=title,
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
    note_record = await update_note_service(
        session,
        user=user,
        filename=filename,
        content=note.content,
    )
    return NoteUpdateResponse(
        filename=note_record.filename,
        updated=True
    )


@file_router.put(
    "/note/sync",
    response_model=NoteBulkSyncResponse,
    status_code=200)
async def sync_notes(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    count = await sync_user_notes_service(session, user=user)
    return NoteBulkSyncResponse(
        count=count,
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
    await delete_note_service(session, user=user, filename=filename)
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
    file_record = await get_file_status_service(session, user=user, filename=filename)
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
    file_path, original_filename, content_type = await get_file_for_download_service(
        session,
        user=user,
        filename=filename,
    )
    return FileResponse(
        path=file_path,
        filename=original_filename,
        media_type=content_type
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
    await delete_file_service(session, user=user, filename=filename)
    return ResourceDeletedResponse(status="deleted")
