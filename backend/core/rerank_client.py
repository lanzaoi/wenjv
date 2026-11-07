"""BGE Reranker v2-m3 client — supports local ONNX and cloud (SiliconFlow) with fail-open and local-fallback architecture.

Returns:
    list[dict]  — sorted results [{"index": int, "relevance_score": float}, ...] if succeeds
    None        — any failure (HTTP error, timeout, missing key, disabled)
                   Caller MUST preserve original results on None.

Never returns [] to signal failure — [] is ambiguous (could mean "no relevant docs").
"""
import os
import asyncio
import logging
import httpx
import numpy as np
from backend.config import settings

logger = logging.getLogger(settings.LOGGER_NAME)

_local_engine = None


class LocalBGERerankerOnnxEngine:
    def __init__(self, model_dir: str):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.model_dir = str(model_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = min(14, os.cpu_count() or 4)
        opts.inter_op_num_threads = 2
        model_path = os.path.join(self.model_dir, "model_quantized.onnx")
        if not os.path.exists(model_path):
            model_path = os.path.join(self.model_dir, "model.onnx")

        self.session = ort.InferenceSession(
            model_path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        logger.info(f"Initialized Local BGE Reranker ONNX from {self.model_dir}")

    def rerank_sync(self, query: str, documents: list[str]) -> list[dict]:
        if not documents:
            return []
        micro_batch_size = 8
        all_scores = []
        for i in range(0, len(documents), micro_batch_size):
            batch_docs = documents[i : i + micro_batch_size]
            pairs = [[query, doc] for doc in batch_docs]
            features = self.tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="np",
            )
            outputs = self.session.run(
                ["logits"],
                {
                    "input_ids": features["input_ids"],
                    "attention_mask": features["attention_mask"],
                },
            )
            logits = outputs[0].flatten()
            scores = 1.0 / (1.0 + np.exp(-logits))
            all_scores.extend(scores.tolist())

        results = [
            {"index": idx, "relevance_score": float(score)}
            for idx, score in enumerate(all_scores)
        ]
        results.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
        return results


def _get_local_reranker():
    global _local_engine
    if _local_engine is None:
        from pathlib import Path
        model_dir = getattr(settings, "LOCAL_RERANK_MODEL_DIR", "models/bge_reranker_v2_m3")
        p = Path(model_dir)
        if not p.is_absolute():
            project_root = Path(__file__).resolve().parent.parent.parent
            candidate = project_root / p
            if candidate.exists():
                p = candidate
        _local_engine = LocalBGERerankerOnnxEngine(str(p))
    return _local_engine


async def rerank(query: str, documents: list[str]) -> list[dict] | None:
    """Call rerank (Local ONNX or SiliconFlow). Returns None on any failure (fail-open)."""
    if not documents:
        return None

    if not getattr(settings, "RERANK_ENABLED", False):
        return None

    provider = getattr(settings, "RERANK_PROVIDER", "local_onnx")
    if provider == "local_onnx":
        try:
            engine = _get_local_reranker()
            return await asyncio.to_thread(engine.rerank_sync, query, documents)
        except Exception as e:
            logger.warning(f"Local ONNX rerank failed (fail-open): {e}")
            return None

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
            try:
                from backend.core.observability import increment_api_count
                await asyncio.to_thread(increment_api_count, provider, "rerank")
            except Exception as ex:
                logger.warning(f"Failed to increment rerank api count: {ex}")
            response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            results.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
            return results
    except Exception as e:
        logger.warning(f"Rerank API failed (fail-open, preserving original order): {e}")
        return None
