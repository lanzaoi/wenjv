import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.api.dependencies import current_active_user
from backend.api.models import User
from backend.config import settings
from backend.core.logging import get_logger
from backend.core.visual_assets import compress_and_standardize_image

logger = get_logger()

attachments_router = APIRouter(prefix="/chat/attachments", tags=["chat"])


class AttachmentResponse(BaseModel):
    media_url: str
    media_id: str
    filename: str
    content_type: str
    size: int


@attachments_router.post("", response_model=AttachmentResponse)
async def upload_chat_attachment(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    user: User = Depends(current_active_user),
):
    """
    Upload and persist an image attachment for multimodal chat sessions.
    Saves image under UPLOAD_DIR/mm_assets/sessions/{session_id}/
    Returns a persistent media_url that can be referenced across multi-turn chats.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(file.filename).suffix.lower()
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported image extension {ext}. Allowed: {sorted(allowed_exts)}")

    import asyncio
    max_bytes = getattr(settings, "MAX_UPLOAD_BYTES", 25 * 1024 * 1024)

    # Chunked read to protect memory from OOM (H4)
    chunks = []
    total_size = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Attachment size exceeds limit of {max_bytes // (1024 * 1024)}MB",
            )
        chunks.append(chunk)

    raw_bytes = b"".join(chunks)
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty file content")

    def _verify_and_compress(data: bytes) -> bytes:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(data)) as pil_img:
            pil_img.verify()
        return compress_and_standardize_image(data, max_dimension=1568, quality=90)

    try:
        # Offload PIL verification and compression to worker thread (H3)
        std_bytes = await asyncio.to_thread(_verify_and_compress, raw_bytes)
    except Exception as e:
        logger.warning(f"Invalid image uploaded: {e}")
        raise HTTPException(status_code=400, detail="File is not a valid image")

    # Resolve target directory with user_id tenant isolation (H1)
    safe_session = str(session_id or uuid.uuid4().hex[:12])
    safe_session = "".join(c for c in safe_session if c.isalnum() or c in ("-", "_")) or "common"
    uid_str = str(user.id)

    target_dir = Path(settings.UPLOAD_DIR) / "mm_assets" / "sessions" / uid_str / safe_session
    target_dir.mkdir(parents=True, exist_ok=True)

    media_id = f"{uuid.uuid4().hex[:8]}_{Path(file.filename).stem[:30]}.jpg"
    target_path = target_dir / media_id

    def _write_file(path: Path, data: bytes):
        with open(path, "wb") as f:
            f.write(data)

    await asyncio.to_thread(_write_file, target_path, std_bytes)

    # Build relative asset url with user_id
    rel_path = f"mm_assets/sessions/{uid_str}/{safe_session}/{media_id}"
    media_url = f"/api/documents/assets/image?path={rel_path}"

    return AttachmentResponse(
        media_url=media_url,
        media_id=media_id,
        filename=file.filename,
        content_type="image/jpeg",
        size=len(std_bytes),
    )
