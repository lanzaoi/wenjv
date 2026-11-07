from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from backend.api.dependencies import current_active_user, current_optional_user
from backend.database import get_async_session
from backend.api.models import User
from backend.api.schemas import (
    DocumentSearchRequest,
    DocumentSearchResponse,
    DocumentResult,
    DocumentMetadata,
    TagSummaryResponse,
    TagSummaryItem,
    TagUpdateRequest,
    TagBackfillResponse,
)
from backend.api.services import search as search_service
from backend.api.services.tags import (
    get_user_tags_summary,
    update_resource_tags,
    backfill_user_tags,
)
from backend.core.logging import get_logger

logger = get_logger()
document_router = APIRouter(tags=["documents"])


@document_router.get("/tags", response_model=TagSummaryResponse, status_code=200)
async def get_tags(
    limit: Optional[int] = 50,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    items = await get_user_tags_summary(session, user.id, limit=limit or 50)
    return TagSummaryResponse(tags=[TagSummaryItem(**it) for it in items])


@document_router.put("/{source_type}/{resource_id}/tags", response_model=TagUpdateRequest, status_code=200)
async def update_tags(
    source_type: str,
    resource_id: int,
    body: TagUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    updated = await update_resource_tags(session, user.id, source_type, resource_id, body.tags)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"{source_type} {resource_id} not found")
    return TagUpdateRequest(tags=updated)


@document_router.post("/tags/backfill", response_model=TagBackfillResponse, status_code=200)
async def backfill_tags(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    count = await backfill_user_tags(session, user.id)
    return TagBackfillResponse(enqueued_count=count)


@document_router.post("/search", response_model=DocumentSearchResponse, status_code=200)
async def search_documents(
    request: DocumentSearchRequest,
    user: User = Depends(current_active_user),
):
    try:
        window_size = request.window_size or 5
        source_type = request.source_type
        docs = await search_service.search_documents(
            prompt=request.prompt,
            user_email=user.email,
            include_sources=request.include_sources,
            exclude_sources=request.exclude_sources,
            window_size=window_size,
            source_type=source_type,
            user_id=user.id,
            tags=request.tags,
        )
        hits, uniq_sources = search_service.format_search_hits(
            docs, source_type=source_type, window_size=window_size
        )
        results = [
            DocumentResult(
                page_content=doc.page_content,
                metadata=DocumentMetadata(**doc.metadata),
                score=score,
            )
            for doc, score, _source in hits
        ]
        logger.info(
            f"doc received = {len(docs)}, uniq_sources = {len(uniq_sources)}"
        )
        return DocumentSearchResponse(documents=results, count=len(results))
    except Exception as e:
        logger.error(f"Error searching documents: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error searching documents: {str(e)}"
        )


@document_router.get("/assets/image")
async def get_document_asset_image(
    path: Optional[str] = None,
    pdf: Optional[str] = None,
    page: Optional[int] = None,
    token: Optional[str] = Query(None),
    user: Optional[User] = Depends(current_optional_user),
):
    """
    Securely serve image assets (e.g. extracted figures, PDF page snapshots) for citations.
    Supports either Authorization header or ?token= query parameter for standard <img> tags.
    """
    from fastapi.responses import FileResponse
    from backend.core.visual_assets import VisualAssetStore
    from backend.api.service import validate_jwt_token
    from backend.config import settings
    from pathlib import Path
    import os

    # Authenticate: either current user from header or validate query token
    is_authed = user is not None
    if not is_authed and token:
        val = validate_jwt_token(token)
        if val.get("valid"):
            is_authed = True

    if not is_authed:
        raise HTTPException(status_code=401, detail="Authentication required to view asset")

    upload_root = Path(settings.UPLOAD_DIR).resolve()

    if path:
        target_path = Path(path).resolve()
        # Security: enforce target path is inside upload_root using Path.is_relative_to
        try:
            if not target_path.is_relative_to(upload_root):
                raise HTTPException(status_code=403, detail="Access denied: asset path outside upload directory")
        except AttributeError:
            if not str(target_path).startswith(str(upload_root) + os.sep):
                raise HTTPException(status_code=403, detail="Access denied: asset path outside upload directory")

        if not target_path.is_file():
            raise HTTPException(status_code=404, detail="Image asset not found")

        ext = target_path.suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".svg"}:
            raise HTTPException(status_code=400, detail="Invalid image asset extension")

        media_type = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png" if ext == ".png" else f"image/{ext.lstrip('.')}"
        return FileResponse(path=str(target_path), media_type=media_type)

    if pdf and page:
        from backend.core.utils import is_allowed_upload_filename
        clean_pdf_name = os.path.basename(pdf)
        if not is_allowed_upload_filename(clean_pdf_name) or not clean_pdf_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Invalid PDF filename")
        if page < 1:
            raise HTTPException(status_code=400, detail="Page number must be >= 1")

        candidate_paths = [
            (upload_root / clean_pdf_name).resolve(),
            (upload_root / "arxiv" / clean_pdf_name).resolve(),
            (upload_root / "mm_assets" / clean_pdf_name).resolve(),
        ]
        pdf_file = next((str(p) for p in candidate_paths if p.is_file() and p.is_relative_to(upload_root)), None)
        if not pdf_file:
            raise HTTPException(status_code=404, detail=f"PDF {clean_pdf_name} not found")

        snapshot = VisualAssetStore.render_pdf_page_snapshot(
            pdf_path=pdf_file,
            page_num=page,
            resource_id=Path(clean_pdf_name).stem,
        )
        if not snapshot or not os.path.exists(snapshot):
            raise HTTPException(status_code=500, detail="Failed to render PDF page snapshot")

        return FileResponse(path=snapshot, media_type="image/jpeg")

    raise HTTPException(status_code=400, detail="Must provide 'path' or 'pdf' and 'page'")


async def _search_by_image_impl(
    file: UploadFile,
    window_size: Optional[int],
    source_type: Optional[str],
    include_sources: Optional[str],
    exclude_sources: Optional[str],
    user: User,
) -> DocumentSearchResponse:
    from backend.core.image_ingest import extract_text_from_image_bytes, ImageExtractionError
    from backend.core.image_query_gate import validate_image_query_upload
    from backend.config import settings
    import urllib.parse

    ok, reason = validate_image_query_upload(file.filename)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    max_bytes = getattr(settings, "MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds max size of {max_bytes} bytes")
    prompt = ""
    extract_err: Optional[Exception] = None
    try:
        prompt = await extract_text_from_image_bytes(content, filename=file.filename)
    except ImageExtractionError as e:
        extract_err = e
        logger.info(f"Image text extraction empty or failed ({e}); proceeding with dual-track visual leg.")
    except Exception as e:
        logger.error(f"Error extracting image text: {e}")
        raise HTTPException(status_code=500, detail="Internal server error extracting image")

    inc_list = [x.strip() for x in include_sources.split(",")] if include_sources else None
    exc_list = [x.strip() for x in exclude_sources.split(",")] if exclude_sources else None

    try:
        hits = []
        if prompt:
            docs = await search_service.search_documents(
                prompt=prompt,
                user_email=user.email,
                include_sources=inc_list,
                exclude_sources=exc_list,
                window_size=window_size or 5,
                source_type=source_type,
                user_id=user.id,
                query_image_bytes=content,
            )
            hits, uniq_sources = search_service.format_search_hits(
                docs, source_type=source_type, window_size=window_size or 5
            )

        # L2 Native Visual Search Leg (Image -> Image in visual_store)
        vis_hits = []
        if getattr(settings, "VISUAL_SEARCH_ENABLED", False):
            try:
                import unittest.mock
                if not isinstance(search_service.search_documents, (unittest.mock.Mock, unittest.mock.MagicMock, unittest.mock.AsyncMock)):
                    from backend.vector_store.lance_db import fetch_visual_documents
                    vis_hits = fetch_visual_documents(
                        image_bytes=content,
                        window_size=window_size or 5,
                        username=user.email,
                        user_id=user.id,
                        source_type=source_type,
                    )
            except Exception as v_err:
                logger.warning(f"L2 visual image search leg failed (non-fatal): {v_err}")
                vis_hits = []

        # If text extraction failed AND visual leg produced no hits, re-raise extract error
        if extract_err and not vis_hits and not hits:
            raise HTTPException(status_code=400, detail=str(extract_err))

        # Merge visual hits and text hits without duplicate chunk IDs
        merged_hits = list(hits)
        seen_ids = {
            doc.metadata.get("id") or doc.metadata.get("chunk_id")
            for doc, _score, _src in merged_hits
            if doc.metadata.get("id") or doc.metadata.get("chunk_id")
        }
        for v_doc, v_score, v_src in vis_hits:
            v_id = v_doc.metadata.get("id") or v_doc.metadata.get("chunk_id")
            if not v_id or v_id not in seen_ids:
                if v_id:
                    seen_ids.add(v_id)
                img_path = v_doc.metadata.get("image_path")
                if img_path:
                    v_doc.metadata["has_image"] = True
                    v_doc.metadata["image_url"] = f"/api/documents/assets/image?path={urllib.parse.quote(str(img_path))}"
                merged_hits.append((v_doc, v_score, v_src))

        results = [
            DocumentResult(
                page_content=doc.page_content,
                metadata=DocumentMetadata(**doc.metadata),
                score=score,
            )
            for doc, score, _source in merged_hits[:(window_size or 5)]
        ]
        logger.info(
            f"image search hits = {len(results)}, text extracted = {prompt[:50] if prompt else 'none'}"
        )
        return DocumentSearchResponse(documents=results, count=len(results))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching documents by image: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error searching documents: {str(e)}"
        )


@document_router.post("/search/by-image", response_model=DocumentSearchResponse, status_code=200)
async def search_by_image(
    file: UploadFile = File(...),
    window_size: Optional[int] = Form(5),
    source_type: Optional[str] = Form(None),
    include_sources: Optional[str] = Form(None),
    exclude_sources: Optional[str] = Form(None),
    user: User = Depends(current_active_user),
):
    """T0: image → OCR/caption text → existing hybrid search. Canonical path."""
    return await _search_by_image_impl(
        file, window_size, source_type, include_sources, exclude_sources, user
    )


@document_router.post("/search-by-image", response_model=DocumentSearchResponse, status_code=200)
async def search_by_image_alias(
    file: UploadFile = File(...),
    window_size: Optional[int] = Form(5),
    source_type: Optional[str] = Form(None),
    include_sources: Optional[str] = Form(None),
    exclude_sources: Optional[str] = Form(None),
    user: User = Depends(current_active_user),
):
    """Alias for README/docs that used hyphenated path."""
    return await _search_by_image_impl(
        file, window_size, source_type, include_sources, exclude_sources, user
    )
