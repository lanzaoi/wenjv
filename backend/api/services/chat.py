"""Backend RAG chat: retrieve → prompt → stream Ollama."""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from backend.api.services import search as search_service
from backend.config import settings
from backend.core.logging import get_logger
from backend.core.visual_assets import VisualAssetStore, compress_and_standardize_image

logger = get_logger()


def build_context_block(hits) -> str:
    parts = []
    for i, (doc, score, source) in enumerate(hits, start=1):
        title = doc.metadata.get("title") or doc.metadata.get("filename") or source
        page = doc.metadata.get("page", "")
        parts.append(
            f"[{i}] {title} (page={page}, distance={score:.4f})\n{doc.page_content}"
        )
    return "\n\n---\n\n".join(parts)


def build_messages(
    *,
    question: str,
    context: str,
    history: Optional[List[Dict[str, Any]]] = None,
    current_images: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    if context and context.strip():
        system = {
            "role": "system",
            "content": (
                "You are a document Q&A assistant. Answer using ONLY the provided "
                "context. If the answer is not in the context, say you cannot answer "
                "based on the provided context. Cite sources like [1], [2] when useful."
            ),
        }
        user_content = f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    else:
        system = {
            "role": "system",
            "content": "You are a helpful Q&A assistant.",
        }
        user_content = f"Question: {question}\n\nAnswer:"

    user: Dict[str, Any] = {
        "role": "user",
        "content": user_content,
    }
    if current_images:
        user["images"] = current_images

    messages: List[Dict[str, Any]] = [system]
    if history:
        # Keep last 8 turns. Apply sliding window decay to older images (keep images only for last 2 turns).
        trimmed = history[-8:]
        hist_len = len(trimmed)
        for idx, m in enumerate(trimmed):
            m_copy = dict(m)
            raw_imgs = m_copy.get("images") or []
            # Calculate distance from latest turn: 0 is right before current turn
            dist_from_latest = hist_len - 1 - idx
            if raw_imgs:
                if dist_from_latest < 2:
                    # Recent turns: resolve and retain image payloads
                    resolved_imgs = []
                    for raw_item in raw_imgs:
                        if isinstance(raw_item, dict) and "data" in raw_item:
                            resolved_imgs.append(raw_item)
                        elif isinstance(raw_item, str):
                            res = VisualAssetStore.resolve_image_from_identifier(raw_item)
                            if res:
                                b_data, mime = res
                                b_std = compress_and_standardize_image(b_data, max_dimension=1280)
                                resolved_imgs.append({
                                    "mime_type": mime,
                                    "data": base64.b64encode(b_std).decode("ascii"),
                                    "label": "[历史附图]",
                                })
                    if resolved_imgs:
                        m_copy["images"] = resolved_imgs
                    else:
                        m_copy.pop("images", None)
                else:
                    # Distant turns (>= 2 turns ago): decay heavy images to token-friendly semantic note
                    m_copy.pop("images", None)
                    m_content = m_copy.get("content", "")
                    if "[历史附图" not in m_content:
                        m_copy["content"] = f"{m_content}\n[历史附图: {len(raw_imgs)} 张 (已阅，已衰减)]"
            messages.append(m_copy)

    messages.append(user)
    return messages


async def stream_ollama_chat(
    *,
    model: str,
    messages: List[Dict[str, Any]],
) -> AsyncIterator[str]:
    url = settings.OLLAMA_HOST.rstrip("/") + "/api/chat"
    # Format messages for Ollama, supporting images: [b64_string]
    ollama_messages = []
    for m in messages:
        entry = {"role": m.get("role", "user"), "content": m.get("content", "")}
        imgs = m.get("images")
        if imgs and isinstance(imgs, list):
            b64_list = []
            for img in imgs:
                if isinstance(img, dict) and img.get("data"):
                    b64_list.append(img["data"])
                elif isinstance(img, str):
                    b64_list.append(img)
            if b64_list:
                entry["images"] = b64_list
        ollama_messages.append(entry)

    payload = {"model": model, "messages": ollama_messages, "stream": True}
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
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


def is_vision_model(model_name: str) -> bool:
    """Check if model explicitly supports OpenAI/multimodal image_url format."""
    name = (model_name or "").lower()
    return any(k in name for k in ("vl", "vision", "4o", "gemini", "gemma", "pixtral", "claude"))


async def stream_openai_chat(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    images: Optional[List[Dict[str, str]]] = None,
) -> AsyncIterator[str]:
    provider = getattr(settings, "CHAT_PROVIDER", "openai").lower()
    if provider in ("google", "gemini"):
        async for token in stream_google_chat(model=model, messages=messages, images=images):
            yield token
        return

    api_key = getattr(settings, "CHAT_API_KEY", "")
    api_base = getattr(settings, "CHAT_API_BASE", "").rstrip("/")
    if not api_key:
        raise ValueError(f"Missing CHAT_API_KEY for CHAT_PROVIDER={getattr(settings, 'CHAT_PROVIDER', '')}.")

    if api_base.endswith("/chat/completions"):
        url = api_base
    else:
        url = f"{api_base}/chat/completions"

    chosen_model = getattr(settings, "CHAT_MODEL", "") or model

    # Check if ANY message in messages has images
    has_any_images = any(bool(m.get("images")) for m in messages if isinstance(m, dict)) or bool(images)
    if has_any_images:
        if not is_vision_model(chosen_model) or chosen_model in ("Qwen/Qwen2.5-7B-Instruct", "mistral:7b-instruct-q4_0"):
            chosen_model = "Qwen/Qwen3-VL-8B-Instruct"

    formatted = []
    for m in messages:
        role = m.get("role", "user")
        text_content = m.get("content", "")
        msg_images = m.get("images") or []

        if role == "user" and (msg_images or (m is messages[-1] and images)):
            eff_images = list(msg_images)
            if m is messages[-1] and images:
                for img in images:
                    if img not in eff_images:
                        eff_images.append(img)

            if is_vision_model(chosen_model):
                parts = []
                for img in eff_images:
                    mime = img.get("mime_type", "image/jpeg") if isinstance(img, dict) else "image/jpeg"
                    b64 = img.get("data", "") if isinstance(img, dict) else str(img)
                    parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
                parts.append({"type": "text", "text": text_content})
                formatted.append({"role": "user", "content": parts})
            else:
                formatted.append({"role": "user", "content": text_content})
        else:
            formatted.append({"role": role, "content": text_content})

    payload = {
        "model": chosen_model,
        "messages": formatted,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    in_reasoning = False
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code == 401:
                raise ValueError("Unauthorized (401) for CHAT_PROVIDER. Check your API key.")
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            if not in_reasoning:
                                in_reasoning = True
                                yield "> 💭 *思考过程*：\n> "
                            yield reasoning.replace("\n", "\n> ")
                        content = delta.get("content")
                        if content:
                            if in_reasoning:
                                in_reasoning = False
                                yield "\n\n"
                            yield content
                except json.JSONDecodeError:
                    continue


async def stream_google_chat(
    *,
    model: str,
    messages: List[Dict[str, str]],
    images: Optional[List[Dict[str, str]]] = None,
) -> AsyncIterator[str]:
    """Stream chat responses from Google Generative Language API (Gemma / Gemini) with visual parts."""
    api_key = getattr(settings, "CHAT_API_KEY", "")
    if not api_key:
        raise ValueError("Missing CHAT_API_KEY for CHAT_PROVIDER=google.")

    model_name = getattr(settings, "CHAT_MODEL", "") or model or "gemma-4-31b-it"
    if model_name.startswith("models/"):
        model_name = model_name[7:]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    # Merge system prompt into first user message to support both Gemma & Gemini seamlessly
    system_text = ""
    contents = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        msg_images = m.get("images") or []

        if role == "system":
            system_text += (content + "\n\n")
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            if system_text:
                content = f"{system_text.strip()}\n\n{content}"
                system_text = ""
            user_parts: List[Dict[str, Any]] = []
            
            eff_images = list(msg_images)
            if m is messages[-1] and images:
                for img in images:
                    if img not in eff_images:
                        eff_images.append(img)

            for img in eff_images:
                mime = img.get("mime_type", "image/jpeg") if isinstance(img, dict) else "image/jpeg"
                b64 = img.get("data", "") if isinstance(img, dict) else str(img)
                user_parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64,
                    }
                })
            user_parts.append({"text": content})
            contents.append({"role": "user", "parts": user_parts})

    if system_text:
        contents.insert(0, {"role": "user", "parts": [{"text": system_text.strip()}]})

    payload = {"contents": contents}

    async with httpx.AsyncClient(timeout=120.0) as client:
        last_exc = None
        data = None
        for attempt in range(3):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code in (401, 403):
                    raise ValueError(f"Auth error ({resp.status_code}) for Google API. Check CHAT_API_KEY.")
                if resp.status_code in (500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                break

        if data is None and last_exc is not None:
            sf_key = getattr(settings, "RERANK_API_KEY", "") or getattr(settings, "EMBEDDING_API_KEY", "")
            if sf_key and "sk-" in sf_key:
                logger.warning(f"Google API unavailable ({last_exc}), activating SiliconFlow HA fallback.")
                sf_url = "https://api.siliconflow.cn/v1/chat/completions"
                sf_headers = {"Authorization": f"Bearer {sf_key}", "Content-Type": "application/json"}
                
                sf_model = "Qwen/Qwen3-VL-8B-Instruct" if (images or any(m.get("images") for m in messages)) else "Qwen/Qwen2.5-7B-Instruct"
                sf_messages = []
                for m in messages:
                    role = m.get("role", "user")
                    text_content = m.get("content", "")
                    msg_images = m.get("images") or []
                    if role == "user" and (msg_images or (m is messages[-1] and images)):
                        eff_images = list(msg_images)
                        if m is messages[-1] and images:
                            for img in images:
                                if img not in eff_images:
                                    eff_images.append(img)
                        parts = []
                        for img in eff_images:
                            mime = img.get("mime_type", "image/jpeg") if isinstance(img, dict) else "image/jpeg"
                            b64 = img.get("data", "") if isinstance(img, dict) else str(img)
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"}
                            })
                        parts.append({"type": "text", "text": text_content})
                        sf_messages.append({"role": "user", "content": parts})
                    else:
                        sf_messages.append({"role": role, "content": text_content})

                sf_payload = {
                    "model": sf_model,
                    "messages": sf_messages,
                    "stream": True,
                }
                async with httpx.AsyncClient(timeout=60.0) as sf_client:
                    async with sf_client.stream("POST", sf_url, json=sf_payload, headers=sf_headers) as sf_resp:
                        sf_resp.raise_for_status()
                        async for line in sf_resp.aiter_lines():
                            line = line.strip()
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                d = json.loads(data_str)
                                c = d.get("choices", [{}])[0].get("delta", {}).get("content")
                                if c:
                                    yield c
                            except json.JSONDecodeError:
                                continue
                return
            raise last_exc

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for p in parts:
                if p.get("thought"):
                    continue
                t = p.get("text")
                if t:
                    # Stream tokens in chunks for smooth typing effect
                    chunk_size = 4
                    for i in range(0, len(t), chunk_size):
                        yield t[i:i + chunk_size]
                        await asyncio.sleep(0.01)


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
    tags: Optional[List[str]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    use_rag: bool = True,
    query_image_bytes: Optional[bytes] = None,
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
            docs = await search_service.search_documents(
                prompt=question,
                user_email=user_email,
                include_sources=include_sources,
                exclude_sources=exclude_sources,
                window_size=window_size,
                source_type=source_type,
                user_id=user_id,
                tags=tags,
                query_image_bytes=query_image_bytes,
            )
            hits, _ = search_service.format_search_hits(
                docs, source_type=source_type, window_size=window_size
            )
            for i, (doc, score, source) in enumerate(hits, start=1):
                img_path = doc.metadata.get("image_path")
                img_url = doc.metadata.get("image_url")
                has_img = bool(
                    img_path
                    or (
                        str(doc.metadata.get("filename") or "").lower().endswith(".pdf")
                        and doc.metadata.get("page")
                    )
                )
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
                        "tag_matched": doc.metadata.get("tag_matched", False),
                        "tag_fallback": doc.metadata.get("tag_fallback", False),
                        "has_image": has_img,
                        "image_path": img_path,
                        "image_url": img_url,
                    }
                )
        yield {"type": "citations", "citations": citations}

        if use_rag and not hits and getattr(settings, "RAG_REFUSE_ON_EMPTY", True):
            yield {"type": "token", "content": "抱歉，知识库中未找到相关依据，无法回答该问题。"}
            yield {"type": "done"}
            return

        if use_rag and getattr(settings, "LOST_IN_THE_MIDDLE_ENABLED", True) and len(hits) > 2:
            from backend.api.services.search import arrange_lost_in_the_middle
            context_hits = arrange_lost_in_the_middle(hits)
        else:
            context_hits = hits

        # Resolve L3 visual evidence from retrieved hits (max 3 images)
        images_payload: List[Dict[str, str]] = []

        if query_image_bytes:
            std_query = compress_and_standardize_image(query_image_bytes, max_dimension=1280)
            images_payload.append({
                "mime_type": "image/jpeg",
                "data": base64.b64encode(std_query).decode("ascii"),
                "label": "[用户查询原图]",
            })

        if use_rag and context_hits:
            visual_evidences = VisualAssetStore.resolve_hit_images(context_hits, max_images=3)
            for ve in visual_evidences:
                images_payload.append({
                    "mime_type": ve.mime_type,
                    "data": base64.b64encode(ve.image_bytes).decode("ascii"),
                    "label": ve.label,
                })

        context = build_context_block(context_hits) if use_rag else ""
        if images_payload:
            labels_str = ", ".join(img.get("label", "图表") for img in images_payload)
            context += f"\n\n[视觉附图说明]: 已在多模态上下文中挂载 {len(images_payload)} 张高分辨率视觉证据 ({labels_str})，请结合图中几何/版面/数值直接作答。"

        messages = build_messages(
            question=question,
            context=context,
            history=history,
            current_images=images_payload or None,
        )
        chat_provider = getattr(settings, "CHAT_PROVIDER", "ollama").lower()
        if chat_provider == "ollama":
            stream_gen = stream_ollama_chat(model=model, messages=messages)
        else:
            stream_gen = stream_openai_chat(model=model, messages=messages, images=images_payload or None)

        async for token in stream_gen:
            yield {"type": "token", "content": token}
        yield {"type": "done"}
    except Exception as e:
        logger.error(f"rag_chat_events error: {e}")
        yield {"type": "error", "message": str(e)}
