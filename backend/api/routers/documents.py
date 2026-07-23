from fastapi import APIRouter, Depends, HTTPException
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
        docs = search_service.search_documents(
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
