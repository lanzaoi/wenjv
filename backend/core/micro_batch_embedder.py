# backend/core/micro_batch_embedder.py
"""
Cross-document micro-batch embedding aggregator using in-memory asyncio.Queue.
Batches chunk embedding requests across concurrent document ingestion tasks
(up to batch_size chunks or timeout_ms window) to saturate HTTP keep-alive connections.
"""
from __future__ import annotations

import asyncio
import time
from typing import List, Optional, Any
from dataclasses import dataclass
from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()


@dataclass
class EmbeddingRequestItem:
    text: str
    future: asyncio.Future
    created_at: float


class MicroBatchEmbedder:
    _instance: Optional["MicroBatchEmbedder"] = None

    def __init__(
        self,
        base_embedder: Any,
        batch_size: int = 32,
        timeout_ms: float = 50.0,
    ):
        self.base_embedder = base_embedder
        self.batch_size = max(batch_size, 1)
        self.timeout_sec = max(timeout_ms, 1.0) / 1000.0
        self._queue: Optional[asyncio.Queue[EmbeddingRequestItem]] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        MicroBatchEmbedder._instance = self

    @classmethod
    def get_instance(cls) -> Optional["MicroBatchEmbedder"]:
        return cls._instance

    @classmethod
    def set_active_loop(cls, loop: asyncio.AbstractEventLoop):
        if cls._instance:
            cls._instance._init_loop(loop)

    def _init_loop(self, loop: asyncio.AbstractEventLoop):
        if self._loop != loop or self._worker_task is None or self._worker_task.done():
            self._loop = loop
            self._queue = asyncio.Queue()
            self._worker_task = loop.create_task(self._aggregator_loop())

    def _ensure_worker(self) -> Optional[asyncio.AbstractEventLoop]:
        try:
            loop = asyncio.get_running_loop()
            self._init_loop(loop)
            return loop
        except RuntimeError:
            return self._loop if (self._loop and self._loop.is_running()) else None

    async def _aggregator_loop(self):
        """Worker loop that collects items and flushes when batch is full or timeout expires."""
        while True:
            try:
                if self._queue is None:
                    break
                first_item = await self._queue.get()
                items: List[EmbeddingRequestItem] = [first_item]
                deadline = time.perf_counter() + self.timeout_sec

                while len(items) < self.batch_size:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                        items.append(item)
                    except asyncio.TimeoutError:
                        break

                await self._process_batch(items)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in MicroBatchEmbedder aggregator loop: {e}")

    async def _process_batch(self, items: List[EmbeddingRequestItem]):
        texts = [it.text for it in items]
        try:
            vectors = await asyncio.to_thread(self.base_embedder.embed_documents, texts)
            for item, vec in zip(items, vectors):
                if not item.future.done():
                    item.future.set_result(vec)
        except Exception as exc:
            logger.error(f"MicroBatchEmbedder batch execution failed: {exc}")
            for item in items:
                if not item.future.done():
                    item.future.set_exception(exc)

    async def embed_documents_async(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        loop = self._ensure_worker()
        if loop is None or self._queue is None:
            return await asyncio.to_thread(self.base_embedder.embed_documents, texts)

        futures = []
        now = time.perf_counter()
        for t in texts:
            fut = loop.create_future()
            item = EmbeddingRequestItem(text=t, future=fut, created_at=now)
            await self._queue.put(item)
            futures.append(fut)

        results = await asyncio.gather(*futures)
        return list(results)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Sync interface: if running inside a thread with an active loop, dispatch to loop."""
        if not texts:
            return []

        # If micro-batching is explicitly disabled, bypass
        batch_size = getattr(settings, "INGESTION_MICRO_BATCH_SIZE", 32)
        if not batch_size or batch_size <= 1:
            return self.base_embedder.embed_documents(texts)

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        # Dispatch to aggregator loop ONLY when called from a worker thread (running_loop is None)
        # while the main event loop (self._loop) is running on the main thread.
        if running_loop is None and self._loop is not None and self._loop.is_running():
            try:
                coro = self.embed_documents_async(texts)
                fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
                return fut.result(timeout=60.0)
            except Exception as e:
                logger.debug(f"MicroBatchEmbedder threadsafe dispatch skipped: {e}")

        # Synchronous fallback
        return self.base_embedder.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.base_embedder.embed_query(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base_embedder, name)
