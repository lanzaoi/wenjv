import httpx
import logging
from backend.config import settings

logger = logging.getLogger(settings.LOGGER_NAME)

async def rerank(query: str, documents: list[str]) -> list[dict]:
    """
    Calls the SiliconFlow rerank API.
    Returns sorted docs with relevance_score. Empty result on any error (fail-open).
    """
    if not documents:
        return []
        
    if not getattr(settings, "RERANK_ENABLED", False):
        return []
        
    provider = getattr(settings, "RERANK_PROVIDER", "siliconflow")
    if provider != "siliconflow":
        # Currently only siliconflow is supported
        return []
        
    api_key = getattr(settings, "RERANK_API_KEY", "")
    if not api_key:
        api_key = getattr(settings, "EMBEDDING_API_KEY", "")
        
    if not api_key:
        logger.warning("Rerank API key is empty and EMBEDDING_API_KEY is also empty. Reranking will be skipped.")
        return []
        
    api_base = getattr(settings, "RERANK_API_BASE", "")
    if not api_base:
        api_base = getattr(settings, "EMBEDDING_API_BASE", "")
    if not api_base:
        api_base = "https://api.siliconflow.cn/v1"
        
    model = getattr(settings, "RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    timeout = getattr(settings, "RERANK_TIMEOUT_SECONDS", 8)
    
    url = f"{api_base.rstrip('/')}/rerank"
    
    payload = {
        "model": model,
        "query": query,
        "documents": documents
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            # The API usually returns results sorted by relevance_score, but we can ensure it
            results.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
            return results
    except Exception as e:
        logger.warning(f"Rerank API failed (fail-open): {e}")
        return []
