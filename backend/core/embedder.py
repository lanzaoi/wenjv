import httpx
import time
from typing import List
from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()


class HTTPOpenAIEmbeddings:
    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._max_retries = 3
        self._retry_backoff = 1.5  # seconds base

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
            "Content-Type": "application/json",
        }

        # Compute expected output dims for zero-vector fallback
        dims = getattr(settings, "EMBEDDINGS_DIMENSION", 1024)
        is_single = isinstance(input_data, str)
        inputs = [input_data] if is_single else list(input_data)

        # Truncate long inputs (>1200 chars) to avoid SiliconFlow 400
        safe_inputs = [t[:1200] if len(t) > 1200 else t for t in inputs]
        # Filter out empty strings (SiliconFlow rejects them)
        safe_inputs = [t if t.strip() else " " for t in safe_inputs]

        payload = {
            "model": self.model,
            "input": safe_inputs[0] if is_single else safe_inputs,
        }

        last_err = None
        for attempt in range(1, self._max_retries + 1):
            try:
                try:
                    from backend.core.observability import increment_api_count

                    provider_name = getattr(settings, "EMBEDDING_PROVIDER", "siliconflow").lower()
                    increment_api_count(provider_name, "embed")
                except Exception as ex:
                    logger.warning(f"Failed to increment embedding api count: {ex}")

                with httpx.Client(timeout=60.0) as client:
                    response = client.post(url, headers=headers, json=payload)

                if response.status_code == 401:
                    raise ValueError(
                        f"Unauthorized (401) for EMBEDDING_PROVIDER={settings.EMBEDDING_PROVIDER}. "
                        "Check your API key."
                    )

                # Retry-able HTTP statuses
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    last_err = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.warning(
                        f"Embedding API {last_err} (attempt {attempt}/{self._max_retries})"
                    )
                    if attempt < self._max_retries:
                        time.sleep(self._retry_backoff * attempt)
                        continue
                    logger.error(f"Embedding API error after retries: {last_err}")
                    zero = [0.0] * dims
                    return [zero for _ in inputs]

                if response.status_code != 200:
                    error_msg = response.text[:300]
                    logger.error(f"Embedding API error {response.status_code}: {error_msg}")
                    zero = [0.0] * dims
                    return [zero for _ in inputs]

                data = response.json()
                embeddings = [item["embedding"] for item in data["data"]]
                return embeddings

            except ValueError:
                # Auth / config — do not swallow
                raise
            except httpx.RequestError as e:
                last_err = str(e)
                logger.warning(
                    f"Embedding API request failed: {e} (attempt {attempt}/{self._max_retries})"
                )
                if attempt < self._max_retries:
                    time.sleep(self._retry_backoff * attempt)
                    continue
                logger.error(f"Embedding API request failed after retries: {e}")
                zero = [0.0] * dims
                return [zero for _ in inputs]

        zero = [0.0] * dims
        return [zero for _ in inputs]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Batch embed; on full-batch zero-vector fail-soft, retry one-by-one."""
        if not texts:
            return []
        vectors = self._call_api(texts)
        dims = getattr(settings, "EMBEDDINGS_DIMENSION", 1024)
        # If batch returned any all-zero, retry those items individually
        out = list(vectors)
        if len(out) != len(texts):
            logger.error(
                f"Embedding count mismatch: got {len(out)} for {len(texts)} texts; padding zeros"
            )
            while len(out) < len(texts):
                out.append([0.0] * dims)
            out = out[: len(texts)]
        for i, vec in enumerate(out):
            if not vec or all(v == 0.0 for v in vec):
                single = self._call_api(texts[i])
                if single and not all(v == 0.0 for v in single[0]):
                    out[i] = single[0]
        return out

    def embed_query(self, text: str) -> List[float]:
        return self._call_api(text)[0]


def get_embedder():
    provider = getattr(settings, "EMBEDDING_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings.EMBEDDINGS_MODEL, base_url=settings.OLLAMA_HOST
        )
    else:
        # Default to OpenAI compatible format
        return HTTPOpenAIEmbeddings(
            api_base=settings.EMBEDDING_API_BASE,
            api_key=settings.EMBEDDING_API_KEY,
            model=settings.EMBEDDINGS_MODEL,
        )
