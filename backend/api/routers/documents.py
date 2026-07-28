from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional
from backend.api.dependencies import current_active_user
from backend.api.models import User
from backend.api.schemas import (
    DocumentSearchRequest,
    DocumentSearchResponse,
    DocumentResult,
    DocumentMetadata,
)
from backend.api.services import search as search_service
from backend.core.logging import get_logger

logger = get_logger()
document_router = APIRouter(tags=["documents"])


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

    ok, reason = validate_image_query_upload(file.filename)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    try:
        content = await file.read()
        prompt = await extract_text_from_image_bytes(content, filename=file.filename)
    except ImageExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error extracting image text: {e}")
        raise HTTPException(status_code=500, detail="Internal server error extracting image")

    inc_list = [x.strip() for x in include_sources.split(",")] if include_sources else None
    exc_list = [x.strip() for x in exclude_sources.split(",")] if exclude_sources else None

    try:
        docs = await search_service.search_documents(
            prompt=prompt,
            user_email=user.email,
            include_sources=inc_list,
            exclude_sources=exc_list,
            window_size=window_size or 5,
            source_type=source_type,
            user_id=user.id,
        )
        hits, uniq_sources = search_service.format_search_hits(
            docs, source_type=source_type, window_size=window_size or 5
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
            f"image search hits = {len(results)}, text extracted = {prompt[:50]}"
        )
        return DocumentSearchResponse(documents=results, count=len(results))
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
