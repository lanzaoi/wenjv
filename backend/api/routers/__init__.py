# backend/api/routers/__init__.py
from backend.api.routers.jobs import job_router
from backend.api.routers.documents import document_router
from backend.api.routers.chat import chat_router
from backend.api.routers.files import file_router
from backend.api.routers.links import link_router

__all__ = [
    "job_router",
    "document_router",
    "chat_router",
    "file_router",
    "link_router",
]
