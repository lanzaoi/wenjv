"""Tests for files and notes router decoupling and HTTP contract verification."""
import asyncio
import io
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.api.dependencies import current_active_user
from backend.database import get_async_session, Base
from backend.api.models import User, FileUpload, Note, ProcessingStatus

USER_A = User(id=1, email="user_a@test.com", username="user_a", is_active=True, is_superuser=False)
USER_B = User(id=2, email="user_b@test.com", username="user_b", is_active=True, is_superuser=False)


async def mock_auth_dependency(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth.split("Bearer ")[-1]
    if token == "token_a":
        return USER_A
    elif token == "token_b":
        return USER_B
    raise HTTPException(status_code=401, detail="Invalid token")


@pytest.fixture
def client_env(tmp_path):
    db_path = tmp_path / "test_files_router.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    from sqlalchemy import create_engine
    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    async_engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_async_session():
        async with session_maker() as session:
            yield session

    note_file = tmp_path / "existing_note.md"
    note_file.write_text("# Hello Note", encoding="utf-8")

    upload_file = tmp_path / "existing_file.txt"
    upload_file.write_text("Hello Text File", encoding="utf-8")

    async def seed():
        async with session_maker() as session:
            note_a = Note(
                id=1,
                title="Existing Note",
                filename="existing_note.md",
                file_path=str(note_file),
                url="/file/note/existing_note.md",
                status=ProcessingStatus.FINISHED,
                user_id=1,
            )
            file_a = FileUpload(
                id=1,
                filename="existing_file.txt",
                original_filename="existing_file.txt",
                file_path=str(upload_file),
                file_url="/file/existing_file.txt",
                status=ProcessingStatus.FINISHED,
                content_type="text/plain",
                user_id=1,
            )
            session.add_all([note_a, file_a])
            await session.commit()

    asyncio.run(seed())

    app.dependency_overrides[current_active_user] = mock_auth_dependency
    app.dependency_overrides[get_async_session] = override_get_async_session

    with patch("backend.api.services.files.vector_store.remove_documents"), \
         patch("backend.api.services.files.queue_document", new_callable=AsyncMock), \
         patch("backend.api.services.notes.queue_document", new_callable=AsyncMock):
        client = TestClient(app)
        yield client, tmp_path

    app.dependency_overrides.clear()


def test_upload_file_rejected_extension(client_env):
    client, _ = client_env
    headers = {"Authorization": "Bearer token_a"}
    files = {"file": ("malicious.exe", b"binarycontent", "application/octet-stream")}
    res = client.post("/file/upload", headers=headers, files=files)
    assert res.status_code == 400
    assert "File type not allowed" in res.json()["detail"]


def test_upload_file_exceeds_max_size(client_env):
    client, _ = client_env
    headers = {"Authorization": "Bearer token_a"}
    from backend.config import settings
    old_max = settings.MAX_UPLOAD_BYTES
    settings.MAX_UPLOAD_BYTES = 10
    try:
        files = {"file": ("large.txt", b"more_than_10_bytes_of_content", "text/plain")}
        res = client.post("/file/upload", headers=headers, files=files)
        assert res.status_code == 413
        assert "exceeds max size" in res.json()["detail"]
    finally:
        settings.MAX_UPLOAD_BYTES = old_max


def test_upload_file_success(client_env):
    client, tmp_path = client_env
    headers = {"Authorization": "Bearer token_a"}
    from backend.config import settings
    old_upload_dir = settings.UPLOAD_DIR
    settings.UPLOAD_DIR = str(tmp_path)
    try:
        files = {"file": ("test_doc.txt", b"plain text document", "text/plain")}
        res = client.post("/file/upload", headers=headers, files=files)
        assert res.status_code == 202
        data = res.json()
        assert "filename" in data
        assert data["status"] == "pending"
        assert "/file/" in data["file_url"]
    finally:
        settings.UPLOAD_DIR = old_upload_dir


def test_list_uploaded_files(client_env):
    client, _ = client_env
    headers_a = {"Authorization": "Bearer token_a"}
    headers_b = {"Authorization": "Bearer token_b"}

    res_a = client.get("/file/?skip=0&limit=10", headers=headers_a)
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["total"] >= 1
    assert len(data_a["files"]) >= 1

    res_b = client.get("/file/?skip=0&limit=10", headers=headers_b)
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["total"] == 0
    assert len(data_b["files"]) == 0


def test_create_and_list_note(client_env):
    client, tmp_path = client_env
    headers = {"Authorization": "Bearer token_a"}

    with patch("backend.api.services.notes.save_file", return_value=(1, tmp_path / "n1.md", "n1.md", True)):
        res = client.post("/file/note", headers=headers, json={"title": "New Note", "content": "Content of new note"})
        assert res.status_code == 202
        data = res.json()
        assert data["title"] == "New Note"
        assert data["status"] == "pending"

    res_list = client.get("/file/note?skip=0&limit=10", headers=headers)
    assert res_list.status_code == 200
    assert res_list.json()["total"] >= 1


def test_get_and_update_note(client_env):
    client, _ = client_env
    headers_a = {"Authorization": "Bearer token_a"}
    headers_b = {"Authorization": "Bearer token_b"}

    # Unauthorized access -> 403
    res_b = client.get("/file/note/existing_note.md", headers=headers_b)
    assert res_b.status_code == 403

    # Authorized access -> 200 markdown
    res_a = client.get("/file/note/existing_note.md", headers=headers_a)
    assert res_a.status_code == 200
    assert "Hello Note" in res_a.text

    # Update note
    with patch("backend.api.services.notes.update_file_with_backup", return_value=True):
        res_patch = client.patch(
            "/file/note/existing_note.md",
            headers=headers_a,
            json={"content": "Updated content"}
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["updated"] is True


def test_sync_and_delete_note(client_env):
    client, _ = client_env
    headers_a = {"Authorization": "Bearer token_a"}

    res_sync = client.put("/file/note/sync", headers=headers_a)
    assert res_sync.status_code == 200
    assert res_sync.json()["updated"] is True

    res_del = client.delete("/file/note/existing_note.md", headers=headers_a)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"


def test_get_file_and_status_and_delete(client_env):
    client, _ = client_env
    headers_a = {"Authorization": "Bearer token_a"}
    headers_b = {"Authorization": "Bearer token_b"}

    # Status polling
    res_status = client.get("/file/status/existing_file.txt", headers=headers_a)
    assert res_status.status_code == 200
    assert res_status.json()["status"] == "finished"

    # Download file - cross user forbidden
    res_b = client.get("/file/existing_file.txt", headers=headers_b)
    assert res_b.status_code == 403

    # Download file - owner ok
    res_a = client.get("/file/existing_file.txt", headers=headers_a)
    assert res_a.status_code == 200
    assert "Hello Text File" in res_a.text

    # Delete file
    res_del = client.delete("/file/existing_file.txt", headers=headers_a)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"
