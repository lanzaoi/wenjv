import json
from typing import List, Optional

from fastapi import APIRouter, Depends
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


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    model: Optional[str] = None
    window_size: Optional[int] = 5
    source_type: Optional[str] = None
    include_sources: Optional[List[str]] = None
    exclude_sources: Optional[List[str]] = None
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
            history = [{"role": m.role, "content": m.content} for m in body.history]
        async for event in chat_service.rag_chat_events(
            question=body.question,
            user_email=user.email,
            user_id=user.id,
            model=body.model,
            window_size=body.window_size or 5,
            source_type=body.source_type,
            include_sources=body.include_sources,
            exclude_sources=body.exclude_sources,
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
