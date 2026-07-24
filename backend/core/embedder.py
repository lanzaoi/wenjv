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
        payload = {
            "model": self.model,
            "input": input_data
        }
        
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, headers=headers, json=payload)
                
                if response.status_code != 200:
                    error_msg = response.text
                    if response.status_code == 401:
                        raise ValueError(
                            f"Unauthorized (401) for EMBEDDING_PROVIDER={settings.EMBEDDING_PROVIDER}. "
                            "Check your API key."
                        )
                    raise ValueError(f"Embedding API error {response.status_code}: {error_msg}")
                
                response.raise_for_status()
                data = response.json()
                
                # OpenAI format returns data as a list of objects with an 'embedding' array
                embeddings = [item["embedding"] for item in data["data"]]
                return embeddings
        except Exception as e:
            logger.error(f"Embedding API failed: {e}")
            raise

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
