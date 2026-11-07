import httpx
import time
from typing import List, Optional
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
        self._client = httpx.Client(
            timeout=60.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )

    def close(self):
        if hasattr(self, "_client") and self._client:
            try:
                self._client.close()
            except Exception:
                pass

    def __del__(self):
        self.close()

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

                if response.status_code == 402:
                    from pathlib import Path
                    if Path("models/bge_m3_onnx/model_quantized.onnx").exists():
                        logger.warning("SiliconFlow balance insufficient (402), activating Local BGE-M3 ONNX fallback.")
                        local_emb = get_local_bge_m3_embedder()
                        return local_emb.embed_documents(inputs)

                    g_key = getattr(settings, "CHAT_API_KEY", "") or getattr(settings, "GEMINI_API_KEY", "")
                    if g_key:
                        logger.warning("SiliconFlow balance insufficient (402), activating Google gemini-embedding-2 fallback.")
                        g_emb = GoogleEmbeddings(api_key=g_key, dimension=dims)
                        return g_emb._call_batch(inputs)

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
        """Batch embed in chunks of 32; on full-batch zero-vector fail-soft, retry one-by-one."""
        if not texts:
            return []

        batch_size = 32
        dims = getattr(settings, "EMBEDDINGS_DIMENSION", 1024)
        all_vectors = []

        for offset in range(0, len(texts), batch_size):
            batch_texts = texts[offset:offset + batch_size]
            vectors = self._call_api(batch_texts)
            out = list(vectors)
            if len(out) != len(batch_texts):
                logger.error(
                    f"Embedding count mismatch: got {len(out)} for {len(batch_texts)} texts; padding zeros"
                )
                while len(out) < len(batch_texts):
                    out.append([0.0] * dims)
                out = out[: len(batch_texts)]
            for i, vec in enumerate(out):
                if not vec or all(v == 0.0 for v in vec):
                    single = self._call_api(batch_texts[i])
                    if single and not all(v == 0.0 for v in single[0]):
                        out[i] = single[0]
            all_vectors.extend(out)

        return all_vectors

    def embed_query(self, text: str) -> List[float]:
        return self._call_api(text)[0]


class GoogleEmbeddings:
    """Native Google Generative Language API embeddings (gemini-embedding-2 1024d)."""

    def __init__(self, api_key: str, model: str = "models/gemini-embedding-2", dimension: int = 1024):
        self.api_key = api_key
        self.model = model if model.startswith("models/") else f"models/{model}"
        self.dimension = dimension

    def _call_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        url = f"https://generativelanguage.googleapis.com/v1beta/{self.model}:batchEmbedContents?key={self.api_key}"
        requests = [
            {
                "model": self.model,
                "outputDimensionality": self.dimension,
                "content": {"parts": [{"text": (t[:1500] if len(t) > 1500 else t) if t.strip() else " "}]}
            }
            for t in texts
        ]
        for attempt in range(4):
            try:
                with httpx.Client(timeout=60.0) as client:
                    resp = client.post(url, json={"requests": requests})
                    if resp.status_code == 429 and attempt < 3:
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    embs = data.get("embeddings", [])
                    return [e.get("values", [0.0] * self.dimension) for e in embs]
            except Exception as e:
                if attempt < 3:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                logger.error(f"Google embedding batch failed: {e}")
                return [[0.0] * self.dimension for _ in texts]
        return [[0.0] * self.dimension for _ in texts]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        batch_size = 32
        out = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            out.extend(self._call_batch(chunk))
        return out

    def embed_query(self, text: str) -> List[float]:
        res = self._call_batch([text])
        return res[0] if res else [0.0] * self.dimension


class LocalBGEM3OnnxEmbeddings:
    """Zero-cloud local BGE-M3 1024d ONNX embedder."""

    def __init__(self, model_dir: str = "models/bge_m3_onnx"):
        from pathlib import Path
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.model_dir = Path(model_dir)
        self.model_path = self.model_dir / "model_quantized.onnx"
        self.tokenizer_path = self.model_dir / "tokenizer.json"
        self.dimension = 1024

        if not self.model_path.exists() or not self.tokenizer_path.exists():
            raise FileNotFoundError(f"Local BGE-M3 ONNX files not found in {self.model_dir}")

        providers = ["CPUExecutionProvider"]

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 14
        opts.inter_op_num_threads = 2
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(str(self.model_path), sess_options=opts, providers=providers)
        self.tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
        self.tokenizer.enable_truncation(max_length=512)
        logger.info(f"Loaded Local BGE-M3 ONNX Embedder from {self.model_dir} (providers: {providers})")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        import numpy as np

        batch_size = 16
        all_vecs = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            encoded_list = [self.tokenizer.encode(t[:1500] if len(t) > 1500 else t) for t in chunk]
            max_len = max(len(e.ids) for e in encoded_list) if encoded_list else 1
            input_ids = np.zeros((len(chunk), max_len), dtype=np.int64)
            attn_mask = np.zeros((len(chunk), max_len), dtype=np.int64)
            for row_idx, e in enumerate(encoded_list):
                l = len(e.ids)
                input_ids[row_idx, :l] = e.ids
                attn_mask[row_idx, :l] = e.attention_mask

            out = self.sess.run(["dense_vecs"], {"input_ids": input_ids, "attention_mask": attn_mask})[0]
            # L2 normalize
            norms = np.linalg.norm(out, axis=-1, keepdims=True)
            norms[norms == 0] = 1e-12
            normalized = (out / norms).tolist()
            all_vecs.extend(normalized)
        return all_vecs

    def embed_query(self, text: str) -> List[float]:
        res = self.embed_documents([text])
        return res[0] if res else [0.0] * self.dimension


_local_bge_m3_instance: Optional[LocalBGEM3OnnxEmbeddings] = None


def get_local_bge_m3_embedder() -> LocalBGEM3OnnxEmbeddings:
    global _local_bge_m3_instance
    if _local_bge_m3_instance is None:
        _local_bge_m3_instance = LocalBGEM3OnnxEmbeddings()
    return _local_bge_m3_instance


def get_embedder():
    provider = getattr(settings, "EMBEDDING_PROVIDER", "ollama").lower()
    from pathlib import Path

    if provider in ("local", "bge_onnx") or (provider == "siliconflow" and Path("models/bge_m3_onnx/model_quantized.onnx").exists()):
        try:
            return get_local_bge_m3_embedder()
        except Exception as e:
            logger.warning(f"Local BGE-M3 ONNX embedder initialization failed ({e}), falling back to {provider}")

    if provider == "ollama":
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            from langchain_community.embeddings import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings.EMBEDDINGS_MODEL, base_url=settings.OLLAMA_HOST
        )
    elif provider in ("google", "gemini"):
        g_key = getattr(settings, "CHAT_API_KEY", "") or getattr(settings, "GEMINI_API_KEY", "")
        return GoogleEmbeddings(
            api_key=g_key,
            model=getattr(settings, "EMBEDDINGS_MODEL", "models/gemini-embedding-2"),
            dimension=getattr(settings, "EMBEDDINGS_DIMENSION", 1024),
        )
    else:
        # Default to OpenAI compatible format
        return HTTPOpenAIEmbeddings(
            api_base=settings.EMBEDDING_API_BASE,
            api_key=settings.EMBEDDING_API_KEY,
            model=settings.EMBEDDINGS_MODEL,
        )
