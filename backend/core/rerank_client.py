"""SiliconFlow BGE Reranker v2-m3 client — fail-open architecture.

Returns:
    list[dict]  — sorted results if API succeeds
    None        — any failure (HTTP error, timeout, missing key, disabled)
                   Caller MUST preserve original results on None.

Never returns [] to signal failure — [] is ambiguous (could mean "no relevant docs").
"""
import httpx
import logging
from backend.config import settings

logger = logging.getLogger(settings.LOGGER_NAME)


async def rerank(query: str, documents: list[str]) -> list[dict] | None:
    """Call SiliconFlow rerank API. Returns None on any failure (fail-open)."""
    if not documents:
        return None

    if not getattr(settings, "RERANK_ENABLED", False):
        return None

    provider = getattr(settings, "RERANK_PROVIDER", "siliconflow")
    if provider != "siliconflow":
        return None

    # Resolve API key: explicit → embedding fallback
    api_key = getattr(settings, "RERANK_API_KEY", "") or getattr(settings, "EMBEDDING_API_KEY", "")
    if not api_key:
        logger.warning("Rerank: no API key configured. Skipping (fail-open).")
        return None

    # Resolve base URL: explicit → embedding fallback → default
    api_base = (
        getattr(settings, "RERANK_API_BASE", "")
        or getattr(settings, "EMBEDDING_API_BASE", "")
        or "https://api.siliconflow.cn/v1"
    )
    # Normalize: strip trailing /embeddings if EMBEDDING_API_BASE includes it
    api_base = api_base.rstrip("/").replace("/embeddings", "")

    model = getattr(settings, "RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    timeout = getattr(settings, "RERANK_TIMEOUT_SECONDS", 8)

    url = f"{api_base}/rerank"
    payload = {"model": model, "query": query, "documents": documents}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            results.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
            return results
    except Exception as e:
        logger.warning(f"Rerank API failed (fail-open, preserving original order): {e}")
        return None
