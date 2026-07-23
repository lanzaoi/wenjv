"""Backend RAG chat: retrieve → prompt → stream Ollama."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from backend.api.services import search as search_service
from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()


def build_context_block(hits) -> str:
    parts = []
    for i, (doc, score, source) in enumerate(hits, start=1):
        title = doc.metadata.get("title") or doc.metadata.get("filename") or source
        page = doc.metadata.get("page", "")
        parts.append(
            f"[{i}] {title} (page={page}, score={score})\n{doc.page_content}"
        )
    return "\n\n---\n\n".join(parts)


def build_messages(
    *,
    question: str,
    context: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    if context and context.strip():
        system = {
            "role": "system",
            "content": (
                "You are a document Q&A assistant. Answer using ONLY the provided "
                "context. If the answer is not in the context, say you cannot answer "
                "based on the provided context. Cite sources like [1], [2] when useful."
            ),
        }
        user = {
            "role": "user",
            "content": (
                f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
            ),
        }
    else:
        system = {
            "role": "system",
            "content": "You are a helpful Q&A assistant.",
        }
        user = {
            "role": "user",
            "content": f"Question: {question}\n\nAnswer:",
        }
    messages = [system]
    if history:
        # keep last few turns only
        messages.extend(history[-8:])
    messages.append(user)
    return messages


async def stream_ollama_chat(
    *,
    model: str,
    messages: List[Dict[str, str]],
) -> AsyncIterator[str]:
    url = settings.OLLAMA_HOST.rstrip("/") + "/api/chat"
    payload = {"model": model, "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = data.get("message") or {}
                content = msg.get("content")
                if content:
                    yield content
                if data.get("done"):
                    break


async def rag_chat_events(
    *,
    question: str,
    user_email: str,
    user_id: int,
    model: Optional[str] = None,
    window_size: int = 5,
    source_type: Optional[str] = None,
    include_sources: Optional[List[str]] = None,
    exclude_sources: Optional[List[str]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    use_rag: bool = True,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Yield dict events:
      {"type":"citations", "citations":[...]}
      {"type":"token", "content":"..."}
      {"type":"error", "message":"..."}
      {"type":"done"}
    """
    model = model or getattr(settings, "DEFAULT_CHAT_MODEL", None) or "mistral:7b-instruct-q4_0"
    try:
        citations = []
        hits = []
        if use_rag:
            docs = search_service.search_documents(
                prompt=question,
                user_email=user_email,
                include_sources=include_sources,
                exclude_sources=exclude_sources,
                window_size=window_size,
                source_type=source_type,
                user_id=user_id,
            )
            hits, _ = search_service.format_search_hits(
                docs, source_type=source_type, window_size=window_size
            )
            for i, (doc, score, source) in enumerate(hits, start=1):
                citations.append(
                    {
                        "index": i,
                        "source": source,
                        "page": doc.metadata.get("page"),
                        "title": doc.metadata.get("title") or doc.metadata.get("filename"),
                        "filename": doc.metadata.get("filename"),
                        "source_type": doc.metadata.get("source_type"),
                        "score": score,
                        "snippet": (doc.page_content or "")[:400],
                        "page_content": doc.page_content,
                    }
                )
        yield {"type": "citations", "citations": citations}

        context = build_context_block(hits) if use_rag else ""
        messages = build_messages(
            question=question, context=context, history=history
        )
        async for token in stream_ollama_chat(model=model, messages=messages):
            yield {"type": "token", "content": token}
        yield {"type": "done"}
    except Exception as e:
        logger.error(f"rag_chat_events error: {e}")
        yield {"type": "error", "message": str(e)}
