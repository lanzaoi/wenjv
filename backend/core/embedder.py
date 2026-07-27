import httpx
from typing import List
from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()

class HTTPOpenAIEmbeddings:
    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _call_api(self, input_data) -> List[List[float]]:
        if not self.api_key:
            raise ValueError(
                f"Missing API key for EMBEDDING_PROVIDER={settings.EMBEDDING_PROVIDER}. "
                "Cannot proceed with embedding."
            )
        
        # Some providers use /v1/embeddings, some just /embeddings.
        # If user provided the full path including /embeddings, use it directly.
        if self.api_base.endswith("/embeddings"):
            url = self.api_base
        else:
            url = f"{self.api_base}/embeddings"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Compute expected output dims for zero-vector fallback
        dims = getattr(settings, "EMBEDDINGS_DIMENSION", 1024)
        is_single = isinstance(input_data, str)
        inputs = [input_data] if is_single else list(input_data)

        # Truncate long inputs (>1200 chars) to avoid SiliconFlow 400
        safe_inputs = [t[:1200] if len(t) > 1200 else t for t in inputs]
        # Filter out empty strings (SiliconFlow rejects them)
        safe_inputs = [t if t.strip() else " " for t in safe_inputs]

        try:
            payload = {
                "model": self.model,
                "input": safe_inputs[0] if is_single else safe_inputs
            }

            with httpx.Client(timeout=60.0) as client:
                try:
                    from backend.core.observability import increment_api_count
                    provider_name = getattr(settings, "EMBEDDING_PROVIDER", "siliconflow").lower()
                    increment_api_count(provider_name, "embed")
                except Exception as ex:
                    logger.warning(f"Failed to increment embedding api count: {ex}")
                response = client.post(url, headers=headers, json=payload)

                if response.status_code != 200:
                    error_msg = response.text[:300]
                    if response.status_code == 401:
                        raise ValueError(
                            f"Unauthorized (401) for EMBEDDING_PROVIDER={settings.EMBEDDING_PROVIDER}. "
                            "Check your API key."
                        )
                    logger.error(f"Embedding API error {response.status_code}: {error_msg}")
                    # Fail-soft: return zero vectors
                    zero = [0.0] * dims
                    return [zero for _ in inputs]

                response.raise_for_status()
                data = response.json()

                # OpenAI format returns data as a list of objects with an 'embedding' array
                embeddings = [item["embedding"] for item in data["data"]]
                return embeddings
        except httpx.RequestError as e:
            logger.error(f"Embedding API request failed: {e}")
            zero = [0.0] * dims
            return [zero for _ in inputs]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._call_api(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._call_api(text)[0]

def get_embedder():
    provider = getattr(settings, "EMBEDDING_PROVIDER", "ollama").lower()
    
    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(
            model=settings.EMBEDDINGS_MODEL, 
            base_url=settings.OLLAMA_HOST
        )
    else:
        # Default to OpenAI compatible format
        return HTTPOpenAIEmbeddings(
            api_base=settings.EMBEDDING_API_BASE,
            api_key=settings.EMBEDDING_API_KEY,
            model=settings.EMBEDDINGS_MODEL
        )
