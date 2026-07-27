# backend/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.router import router as auth_router
from backend.api.routers import (
    file_router,
    link_router,
    job_router,
    document_router,
    chat_router,
)
from backend.api.routers.admin import router as admin_router
from backend.worker.url_processor_recursive import process_recursive_url_queue
from backend.worker.durable_jobs import start_job_workers
from backend.config import settings, is_insecure_default_secret
from backend.database import create_db_and_tables
from backend.core.logging import setup_logging, get_logger
import asyncio
import uvicorn

# Ensure ORM models are registered on Base.metadata before create_all
import backend.api.models  # noqa: F401

logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if is_insecure_default_secret():
        get_logger().warning(
            "Insecure default SECRET_KEY detected. "
            "Set SECRET_KEY in ~/.config/inquisitive/backend.env before any real deployment."
        )
    create_db_and_tables()
    await start_job_workers()
    # Experimental crawl still uses in-memory queue
    asyncio.create_task(process_recursive_url_queue())
    yield


app = FastAPI(title="个人知识库 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(file_router, prefix="/file")
app.include_router(link_router, prefix="/links")
app.include_router(document_router, prefix="/documents")
app.include_router(job_router, prefix="/jobs")
app.include_router(chat_router, prefix="/chat")
app.include_router(admin_router, prefix="/admin")


@app.get("/")
async def root():
    return {"message": "个人知识库 API 运行中"}


@app.get("/ping")
async def ping():
    return {"message": "pong"}


@app.get("/health")
async def health():
    import os, asyncio
    from sqlalchemy import text
    from backend.config import settings
    from backend.database import engine as async_engine

    # DB 探活（异步，不阻塞事件循环）
    db_status = "unreachable"
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        pass

    # LanceDB 探活
    vs_status = "unreachable"
    try:
        lance_dir = settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY
        if os.path.isdir(lance_dir):
            import lancedb
            db = await asyncio.to_thread(lancedb.connect, lance_dir)
            tables = await asyncio.to_thread(db.table_names)
            if settings.VECTOR_STORE_COLLECTION_NAME in tables:
                vs_status = "ready"
            else:
                vs_status = "table_missing"
    except Exception:
        pass

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "db": db_status,
        "vector_store": vs_status,
    }


def start_server():
    uvicorn.run(
        "backend.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        log_level=settings.SERVER_LOG_LEVEL
    )


if __name__ == "__main__":
    start_server()
