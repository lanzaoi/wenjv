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


@app.get("/")
async def root():
    return {"message": "个人知识库 API 运行中"}


@app.get("/ping")
async def ping():
    return {"message": "pong"}


def start_server():
    uvicorn.run(
        "backend.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        log_level=settings.SERVER_LOG_LEVEL
    )


if __name__ == "__main__":
    start_server()
