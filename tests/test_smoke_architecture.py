"""Smoke tests for progressive architecture (no heavy vector/LLM deps)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_key_modules_parse():
    files = [
        "backend/main.py",
        "backend/api/router.py",
        "backend/api/routers/files.py",
        "backend/api/routers/links.py",
        "backend/api/routers/chat.py",
        "backend/api/routers/jobs.py",
        "backend/api/routers/documents.py",
        "backend/worker/durable_jobs.py",
        "backend/parsers/registry.py",
    ]
    for rel in files:
        src = (ROOT / rel).read_text(encoding="utf-8")
        ast.parse(src, filename=rel)


def test_auth_router_is_slim():
    src = (ROOT / "backend/api/router.py").read_text(encoding="utf-8")
    assert "file_router" not in src
    assert "link_router" not in src
    assert "validate_token" in src
    assert "get_auth_router" in src


def test_main_wires_all_routers():
    src = (ROOT / "backend/main.py").read_text(encoding="utf-8")
    for name in (
        "auth_router",
        "file_router",
        "link_router",
        "document_router",
        "job_router",
        "chat_router",
        "lifespan",
        "start_job_workers",
    ):
        assert name in src


def test_files_and_links_routers_exist():
    files_src = (ROOT / "backend/api/routers/files.py").read_text(encoding="utf-8")
    links_src = (ROOT / "backend/api/routers/links.py").read_text(encoding="utf-8")
    assert 'file_router.post("/upload"' in files_src or "@file_router.post" in files_src
    assert "queue_document" in files_src
    assert "queue_link" in links_src
    assert "link_router" in links_src
