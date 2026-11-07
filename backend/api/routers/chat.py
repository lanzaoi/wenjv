import json
from typing import List, Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.dependencies import current_active_user
from backend.api.models import User
from backend.api.services import chat as chat_service
from backend.config import settings

chat_router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str
    images: Optional[List[str]] = None


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    model: Optional[str] = None
    window_size: Optional[int] = 5
    source_type: Optional[str] = None
    include_sources: Optional[List[str]] = None
    exclude_sources: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    history: Optional[List[ChatMessage]] = None
    use_rag: bool = True


@chat_router.post("")
async def chat_rag(
    body: ChatRequest,
    user: User = Depends(current_active_user),
):
    """
    SSE stream of RAG chat events (JSON lines after `data: `).
    Event types: citations | token | error | done
    """

    async def event_gen():
        history = None
        if body.history:
            history = [
                {
                    "role": m.role,
                    "content": m.content,
                    **({"images": m.images} if m.images else {}),
                }
                for m in body.history
            ]
        async for event in chat_service.rag_chat_events(
            question=body.question,
            user_email=user.email,
            user_id=user.id,
            model=body.model,
            window_size=body.window_size or 5,
            source_type=body.source_type,
            include_sources=body.include_sources,
            exclude_sources=body.exclude_sources,
            tags=body.tags,
            history=history,
            use_rag=body.use_rag,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@chat_router.post("/by-image")
async def chat_by_image(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    window_size: Optional[int] = Form(5),
    source_type: Optional[str] = Form(None),
    include_sources: Optional[str] = Form(None),
    exclude_sources: Optional[str] = Form(None),
    use_rag: bool = Form(True),
    history: Optional[str] = Form(None),
    user: User = Depends(current_active_user),
):
    from backend.core.image_ingest import extract_text_from_image_bytes, ImageExtractionError
    from backend.core.image_query_gate import validate_image_query_upload

    ok, reason = validate_image_query_upload(file.filename)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    try:
        max_bytes = getattr(settings, "MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File exceeds max size of {max_bytes} bytes")
        question = await extract_text_from_image_bytes(content, filename=file.filename)
    except ImageExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error extracting image")

    inc_list = [x.strip() for x in include_sources.split(",")] if include_sources else None
    exc_list = [x.strip() for x in exclude_sources.split(",")] if exclude_sources else None

    parsed_history = None
    if history:
        try:
            raw_hist = json.loads(history)
            if isinstance(raw_hist, list):
                parsed_history = []
                for item in raw_hist:
                    if isinstance(item, dict) and "role" in item and "content" in item:
                        h_entry = {"role": str(item["role"]), "content": str(item["content"])}
                        if "images" in item and isinstance(item["images"], list):
                            h_entry["images"] = [str(x) for x in item["images"] if x]
                        parsed_history.append(h_entry)
        except Exception:
            parsed_history = None

    async def event_gen():
        async for event in chat_service.rag_chat_events(
            question=question,
            user_email=user.email,
            user_id=user.id,
            model=model,
            window_size=window_size or 5,
            source_type=source_type,
            include_sources=inc_list,
            exclude_sources=exc_list,
            history=parsed_history,
            use_rag=use_rag,
            query_image_bytes=content,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@chat_router.get("/models")
async def list_ollama_models(user: User = Depends(current_active_user)):
    """Best-effort list of local Ollama models (or fallback for cloud provider)."""
    chat_provider = getattr(settings, "CHAT_PROVIDER", "ollama").lower()
    if chat_provider != "ollama":
        model = getattr(settings, "CHAT_MODEL", "")
        return {"models": [model] if model else []}

    import httpx

    url = settings.OLLAMA_HOST.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}
