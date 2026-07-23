"""
File/note ingestion entrypoints.

New path: durable_jobs.enqueue_document_job + job dispatcher.
Legacy file_processor_queue kept so old call sites don't hard-crash.
"""
import asyncio

from backend.worker.durable_jobs import (
    enqueue_document_job,
    notify_workers,
)

# Backward-compat name used by older imports
file_processor_queue = asyncio.Queue()


async def process_uploaded_file_queue():
    """
    Deprecated drain loop.
    Prefer durable job dispatcher (start_job_workers).
    If something still puts tuples here, wake durable path is not automatic —
    callers should migrate to enqueue_document_job.
    """
    while True:
        try:
            item = await file_processor_queue.get()
            # Best-effort: ignore legacy tuples; durable API is the real path.
            _ = item
            notify_workers()
        except Exception:
            await asyncio.sleep(1)


# Re-export for convenience
__all__ = [
    "file_processor_queue",
    "process_uploaded_file_queue",
    "enqueue_document_job",
]
