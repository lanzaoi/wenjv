"""
Visual / Multimodal Embedder (L2 Cross-Modal Retrieval).
Directly encodes raw image pixels and query text into dense vector space.
Supported Providers:
  1. siglip2_onnx (Local, zero-cloud, INT8 optimized, 768-d).
  2. google (models/gemini-embedding-2, 1024-d / 768-d).
  3. siliconflow (Qwen/Qwen3-VL-Embedding-8B, 1024-d).
Integrates transparent SQLite caching to prevent redundant computations.
"""
from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path
from typing import List, Optional

import httpx

from backend.config import settings
from backend.core.embedding_cache import EmbeddingCache
from backend.core.logging import get_logger
from backend.core.visual_assets import compress_and_standardize_image

logger = get_logger()

_cache = EmbeddingCache()


def _image_key(image_bytes: bytes) -> str:
    """Hash raw/standardized image bytes to a deterministic key for caching."""
    return "img:" + hashlib.sha256(image_bytes).hexdigest()[:24]


def _text_key(text: str) -> str:
    """Hash query text for cross-modal visual embedding cache."""
    return "txt:" + hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:24]


class SigLIP2OnnxEngine:
    """Local, zero-cloud SigLIP 2 Base ONNX inference engine."""

    def __init__(self, model_dir: Optional[str] = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.model_dir = Path(
            model_dir or getattr(settings, "SIGLIP2_ONNX_MODEL_DIR", "models/siglip2_onnx")
        )
        self.vision_path = self.model_dir / "onnx" / "vision_model_int8.onnx"
        self.text_path = self.model_dir / "onnx" / "text_model_int8.onnx"
        self.tokenizer_path = self.model_dir / "tokenizer.json"

        if not self.vision_path.exists() or not self.text_path.exists():
            raise FileNotFoundError(
                f"SigLIP 2 ONNX model files missing in {self.model_dir} "
                f"({self.vision_path.name} / {self.text_path.name})"
            )

        providers = ["CPUExecutionProvider"]

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 14
        opts.inter_op_num_threads = 2
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.v_sess = ort.InferenceSession(str(self.vision_path), sess_options=opts, providers=providers)
        self.t_sess = ort.InferenceSession(str(self.text_path), sess_options=opts, providers=providers)

        self.tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
        self.tokenizer.enable_truncation(max_length=64)
        self.tokenizer.enable_padding(length=64, pad_id=0)
        logger.info(f"Loaded SigLIP 2 Base ONNX Engine from {self.model_dir} (providers: {providers})")

    def embed_images(self, image_bytes_list: List[bytes]) -> List[List[float]]:
        if not image_bytes_list:
            return []
        import numpy as np
        from PIL import Image

        batch_size = 16
        all_vecs = []
        for i in range(0, len(image_bytes_list), batch_size):
            chunk = image_bytes_list[i : i + batch_size]
            processed = []
            for raw in chunk:
                try:
                    im = Image.open(io.BytesIO(raw)).convert("RGB")
                    im_resized = im.resize((224, 224), Image.Resampling.BILINEAR)
                    arr = (np.array(im_resized, dtype=np.float32) / 255.0 - 0.5) / 0.5
                    processed.append(np.transpose(arr, (2, 0, 1)))
                except Exception as e:
                    logger.warning(f"Error preprocessing image for SigLIP2: {e}")
                    processed.append(np.zeros((3, 224, 224), dtype=np.float32))

            batch_tensor = np.array(processed, dtype=np.float32)
            out = self.v_sess.run(["pooler_output"], {"pixel_values": batch_tensor})[0]
            # L2 normalize
            norms = np.linalg.norm(out, axis=-1, keepdims=True)
            norms[norms == 0] = 1e-12
            normalized = (out / norms).tolist()
            all_vecs.extend(normalized)
        return all_vecs

    def embed_text(self, text: str) -> List[float]:
        import numpy as np

        clean = (text or "").strip()
        encoded = self.tokenizer.encode(clean)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        out = self.t_sess.run(["pooler_output"], {"input_ids": input_ids})[0]
        vec = out[0]
        norm = np.linalg.norm(vec)
        if norm == 0:
            norm = 1e-12
        normalized = vec / norm
        return normalized.tolist()


_siglip2_engine_instance: Optional[SigLIP2OnnxEngine] = None


def _get_siglip2_engine() -> SigLIP2OnnxEngine:
    global _siglip2_engine_instance
    if _siglip2_engine_instance is None:
        _siglip2_engine_instance = SigLIP2OnnxEngine()
    return _siglip2_engine_instance


class VisualEmbedder:
    """Deep module providing unified cross-modal dense embeddings."""

    def __init__(self):
        self.provider = getattr(settings, "VISUAL_EMBEDDING_PROVIDER", "siglip2_onnx")
        self.dimension = int(getattr(settings, "VISUAL_EMBEDDING_DIMENSION", 768) or 768)
        self.model_tag = f"{self.provider}-{self.dimension}d"

    def embed_image(self, image_bytes: bytes) -> List[float]:
        """Embed a single image to a float vector."""
        return self.embed_images([image_bytes])[0]

    def embed_images(self, image_bytes_list: List[bytes]) -> List[List[float]]:
        """
        Embed a list of images into vectors, utilizing cache where available.
        """
        if not image_bytes_list:
            return []

        results: List[Optional[List[float]]] = [None] * len(image_bytes_list)
        missing_indices: List[int] = []
        standardized_bytes: List[bytes] = []

        # 1. Check cache first
        for idx, raw in enumerate(image_bytes_list):
            std = compress_and_standardize_image(raw, max_dimension=1280)
            standardized_bytes.append(std)
            key = _image_key(std)
            cached_arr = _cache.get(key, self.model_tag)
            if cached_arr is not None and len(cached_arr) == self.dimension:
                results[idx] = cached_arr.tolist()
            else:
                missing_indices.append(idx)

        if not missing_indices:
            return [r for r in results if r is not None]

        # 2. Compute missing vectors
        if self.provider == "siglip2_onnx":
            try:
                engine = _get_siglip2_engine()
                chunk_bytes = [standardized_bytes[idx] for idx in missing_indices]
                computed_vecs = engine.embed_images(chunk_bytes)
                for idx, vec, raw_b in zip(missing_indices, computed_vecs, chunk_bytes):
                    results[idx] = vec[: self.dimension]
                    key = _image_key(raw_b)
                    _cache.set(key, self.model_tag, results[idx])
                return [r for r in results if r is not None]
            except Exception as e:
                logger.warning(f"Local SigLIP 2 ONNX inference failed ({e}), falling back to cloud providers.")

        # Cloud Fallback (Google -> SiliconFlow)
        batch_size = 16
        for i in range(0, len(missing_indices), batch_size):
            chunk_indices = missing_indices[i : i + batch_size]
            chunk_bytes = [standardized_bytes[idx] for idx in chunk_indices]
            chunk_b64 = [base64.b64encode(b).decode("ascii") for b in chunk_bytes]

            try:
                chunk_vecs = self._call_google_batch_image_embedding(chunk_b64)
                for c_idx, vec, raw_b in zip(chunk_indices, chunk_vecs, chunk_bytes):
                    results[c_idx] = vec[: self.dimension]
                    key = _image_key(raw_b)
                    _cache.set(key, self.model_tag, results[c_idx])
            except Exception as batch_err:
                logger.warning(f"Batch Google image embedding failed ({batch_err}), falling back to single items.")
                for idx in chunk_indices:
                    std_bytes = standardized_bytes[idx]
                    vec = self._embed_single_image_with_fallback(std_bytes)
                    results[idx] = vec[: self.dimension]
                    key = _image_key(std_bytes)
                    _cache.set(key, self.model_tag, results[idx])

        return [r for r in results if r is not None]

    def embed_query_text(self, text: str) -> List[float]:
        """
        Embed query text into cross-modal visual vector space (for Text -> Image search).
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return [0.0] * self.dimension

        key = _text_key(clean_text)
        cached_arr = _cache.get(key, self.model_tag)
        if cached_arr is not None and len(cached_arr) == self.dimension:
            return cached_arr.tolist()

        if self.provider == "siglip2_onnx":
            try:
                engine = _get_siglip2_engine()
                vec = engine.embed_text(clean_text)[: self.dimension]
                _cache.set(key, self.model_tag, vec)
                return vec
            except Exception as e:
                logger.warning(f"Local SigLIP 2 ONNX text inference failed ({e}), falling back to cloud.")

        vec = self._embed_text_with_fallback(clean_text)[: self.dimension]
        _cache.set(key, self.model_tag, vec)
        return vec

    def embed_visual_query(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
    ) -> List[float]:
        """Convenience method: embed either an image query or text query into visual space."""
        if image_bytes:
            return self.embed_image(image_bytes)
        if text:
            return self.embed_query_text(text)
        return [0.0] * self.dimension

    # ──────────────────────────────────────────────────────────────────────────
    # Cloud Provider Implementations (Google Primary, SiliconFlow Fallback)
    # ──────────────────────────────────────────────────────────────────────────

    def _embed_single_image_with_fallback(self, std_bytes: bytes) -> List[float]:
        b64_data = base64.b64encode(std_bytes).decode("ascii")
        g_err = None
        sf_err = None

        try:
            return self._call_google_image_embedding(b64_data)
        except Exception as e:
            g_err = e
            logger.warning(f"Google visual embedding failed, trying SiliconFlow fallback: {g_err}")

        try:
            return self._call_siliconflow_image_embedding(b64_data)
        except Exception as e:
            sf_err = e
            logger.error(f"SiliconFlow visual embedding failed: {sf_err}")
            raise RuntimeError(f"All visual embedding providers failed: Google ({g_err}), SF ({sf_err})")

    def _embed_text_with_fallback(self, text: str) -> List[float]:
        g_err = None
        sf_err = None
        try:
            return self._call_google_text_embedding(text)
        except Exception as e:
            g_err = e
            logger.warning(f"Google visual text embedding failed, trying SiliconFlow fallback: {g_err}")

        try:
            return self._call_siliconflow_text_embedding(text)
        except Exception as e:
            sf_err = e
            logger.error(f"SiliconFlow visual text embedding failed: {sf_err}")
            raise RuntimeError(f"All visual text embedding providers failed: Google ({g_err}), SF ({sf_err})")

    def _call_google_image_embedding(self, b64_data: str) -> List[float]:
        key = getattr(settings, "GEMINI_API_KEY", "") or getattr(settings, "GOOGLE_API_KEY", "")
        if not key:
            raise ValueError("Missing Google API key for visual embedder")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={key}"
        payload = {
            "model": "models/gemini-embedding-2",
            "content": {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64_data,
                        }
                    }
                ]
            },
            "output_dimensionality": self.dimension,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            values = data.get("embedding", {}).get("values", [])
            return values[: self.dimension]

    def _call_google_batch_image_embedding(self, b64_list: List[str]) -> List[List[float]]:
        key = getattr(settings, "GEMINI_API_KEY", "") or getattr(settings, "GOOGLE_API_KEY", "")
        if not key:
            raise ValueError("Missing Google API key for batch visual embedder")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:batchEmbedContents?key={key}"
        requests = []
        for b64_data in b64_list:
            requests.append({
                "model": "models/gemini-embedding-2",
                "content": {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64_data,
                            }
                        }
                    ]
                },
                "output_dimensionality": self.dimension,
            })
        payload = {"requests": requests}

        import time
        max_retries = 3
        backoff = 2.0
        for attempt in range(max_retries):
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 429 and attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                resp.raise_for_status()
                data = resp.json()
                embeddings_data = data.get("embeddings", [])
                results = []
                for item in embeddings_data:
                    values = item.get("values", [])
                    results.append(values[: self.dimension])
                return results
        raise RuntimeError("Google batch image embedding rate limit (429) retries exhausted")

    def _call_google_text_embedding(self, text: str) -> List[float]:
        key = getattr(settings, "GEMINI_API_KEY", "") or getattr(settings, "GOOGLE_API_KEY", "")
        if not key:
            raise ValueError("Missing Google API key for visual embedder")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={key}"
        payload = {
            "model": "models/gemini-embedding-2",
            "content": {
                "parts": [{"text": text}]
            },
            "output_dimensionality": self.dimension,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            values = data.get("embedding", {}).get("values", [])
            return values[: self.dimension]

    def _call_siliconflow_image_embedding(self, b64_data: str) -> List[float]:
        key = getattr(settings, "EMBEDDING_API_KEY", "") or getattr(settings, "RERANK_API_KEY", "")
        if not key:
            raise ValueError("Missing SiliconFlow API key for visual embedder")

        url = "https://api.siliconflow.cn/v1/embeddings"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": "Qwen/Qwen3-VL-Embedding-8B",
            "dimensions": self.dimension,
            "input": [{"image": f"data:image/jpeg;base64,{b64_data}"}],
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            if not items or "embedding" not in items[0]:
                raise ValueError(f"Unexpected SF response format: {data}")
            values = items[0]["embedding"]
            return values[: self.dimension]

    def _call_siliconflow_text_embedding(self, text: str) -> List[float]:
        key = getattr(settings, "EMBEDDING_API_KEY", "") or getattr(settings, "RERANK_API_KEY", "")
        if not key:
            raise ValueError("Missing SiliconFlow API key for visual embedder")

        url = "https://api.siliconflow.cn/v1/embeddings"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": "Qwen/Qwen3-VL-Embedding-8B",
            "dimensions": self.dimension,
            "input": [{"text": text}],
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            if not items or "embedding" not in items[0]:
                raise ValueError(f"Unexpected SF response format: {data}")
            values = items[0]["embedding"]
            return values[: self.dimension]


# Shared instance
_visual_embedder_instance: Optional[VisualEmbedder] = None


def get_visual_embedder() -> VisualEmbedder:
    global _visual_embedder_instance
    if _visual_embedder_instance is None:
        _visual_embedder_instance = VisualEmbedder()
    return _visual_embedder_instance
