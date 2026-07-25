import pytest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.api.dependencies import current_active_user
from backend.database import get_async_session, Base
from backend.api.models import User, Note, IngestionJob, JobStatus, ProcessingStatus
from langchain.schema import Document
from backend.config import settings

# 1. Setup double-user fixture and mock auth dependency
USER_A = User(id=1, email="10000@qq.com", username="user_a", is_active=True, is_superuser=False)
USER_B = User(id=2, email="other@test.com", username="user_b", is_active=True, is_superuser=False)

async def mock_auth_dependency(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth.split("Bearer ")[-1]
    if token == "token_a":
        return USER_A
    elif token == "token_b":
        return USER_B
    else:
        raise HTTPException(status_code=401, detail="Invalid token")

@pytest.fixture(autouse=True)
def setup_isolation_env(tmp_path):
    # Setup SQLite test DB
    db_path = tmp_path / "test_iso.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    
    # Create synchronous DB tables for initial setup
    from sqlalchemy import create_engine
    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    # Create async engine and session maker
    async_engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    async_session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_async_session():
        async with async_session_maker() as session:
            yield session

    # Populate initial database with User A's private resources
    async def seed_data():
        async with async_session_maker() as session:
            # Note A owned by User A
            note_a = Note(
                id=10,
                filename="note_a.md",
                title="Note A",
                user_id=1,
                file_path=str(tmp_path / "note_a.md"),
                status=ProcessingStatus.FINISHED
            )
            # Create dummy file on disk for note A
            (tmp_path / "note_a.md").write_text("# Secret A content", encoding="utf-8")
            
            # Job A owned by User A
            job_a = IngestionJob(
                id=100,
                job_type="note",
                resource_id=10,
                user_id=1,
                user_email="10000@qq.com",
                status=JobStatus.PENDING
            )
            session.add(note_a)
            session.add(job_a)
            await session.commit()

    asyncio.run(seed_data())

    # Override dependencies
    app.dependency_overrides[current_active_user] = mock_auth_dependency
    app.dependency_overrides[get_async_session] = override_get_async_session

    # Mock search service to isolate results by user_id and prevent external LLM/embedding network requests
    async def mock_search_documents(*args, **kwargs):
        user_id = kwargs.get("user_id")
        if user_id == 1:
            return [(Document(
                page_content="Secret A content",
                metadata={"filename": "note_a.md", "source": "http://a", "user_id": "1", "page": "1"}
            ), 0.1)]
        elif user_id == 2:
            return []  # User B gets 0 results
        return []

    with patch("backend.api.routers.documents.search_service.search_documents", side_effect=mock_search_documents), \
         patch("backend.api.services.chat.search_service.search_documents", side_effect=mock_search_documents), \
         patch("backend.api.routers.files.vector_store.remove_documents"):
        yield

    app.dependency_overrides.clear()


def test_api_isolation_matrix():
    """Execute the 8-scenario API isolation test matrix."""
    client = TestClient(app)
    headers_b = {"Authorization": "Bearer token_b"}
    headers_a = {"Authorization": "Bearer token_a"}

    # 1. GET /file/ (or listing endpoint): B without token -> 401
    res1 = client.get("/file/")
    assert res1.status_code == 401

    # 2. POST /documents/search: B token searching A's note -> 0 results (A's note should not appear)
    res2_b = client.post("/documents/search", json={"prompt": "Secret A"}, headers=headers_b)
    assert res2_b.status_code == 200
    assert res2_b.json()["count"] == 0
    assert len(res2_b.json()["documents"]) == 0

    # Verify A can search their own note
    res2_a = client.post("/documents/search", json={"prompt": "Secret A"}, headers=headers_a)
    assert res2_a.status_code == 200
    assert res2_a.json()["count"] == 1
    assert res2_a.json()["documents"][0]["page_content"] == "Secret A content"

    # 3. GET /file/note/{filename}: B token reading A's note -> 404 or 403
    res3 = client.get("/file/note/note_a.md", headers=headers_b)
    assert res3.status_code in [403, 404]

    # 4. PATCH /file/note/{filename}: B modifying A's note -> 404 or 403
    res4 = client.patch("/file/note/note_a.md", json={"title": "hack", "content": "hack"}, headers=headers_b)
    assert res4.status_code in [403, 404]

    # 5. GET /jobs/: B checking jobs -> Only sees B's jobs (or empty)
    res5_b = client.get("/jobs", headers=headers_b)
    assert res5_b.status_code == 200
    assert len(res5_b.json()) == 0

    # Verify A sees their job
    res5_a = client.get("/jobs", headers=headers_a)
    assert res5_a.status_code == 200
    assert len(res5_a.json()) == 1
    assert res5_a.json()[0]["id"] == 100

    # 6. POST /chat: B asking question -> Should not mention A's note content
    # With RAG_REFUSE_ON_EMPTY=True, 0 retrieval results must trigger refusal and no LLM call
    settings.RAG_REFUSE_ON_EMPTY = True
    with patch("backend.api.services.chat.stream_openai_chat") as m_openai, \
         patch("backend.api.services.chat.stream_ollama_chat") as m_ollama:
        res6 = client.post("/chat", json={"question": "What is in note A?", "use_rag": True}, headers=headers_b)
        assert res6.status_code == 200
        content = res6.text
        assert "Secret A content" not in content
        assert "未找到相关依据" in content
        m_openai.assert_not_called()
        m_ollama.assert_not_called()

    # 7. POST /file/upload: anonymous -> 401
    res7 = client.post("/file/upload", files={"file": ("test.txt", b"hello world")})
    assert res7.status_code == 401

    # 8. DELETE /file/note/{filename}: B deleting A's note -> 404 or 403
    res8 = client.delete("/file/note/note_a.md", headers=headers_b)
    assert res8.status_code in [403, 404]
