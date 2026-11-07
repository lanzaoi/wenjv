"""Tests for links router decoupling and HTTP contract verification."""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.api.dependencies import current_active_user
from backend.database import get_async_session, Base
from backend.api.models import User, Link, ProcessingStatus

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
    db_path = tmp_path / "test_links_router.db"
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

    async def seed():
        async with session_maker() as session:
            link_a = Link(
                id=1,
                url="https://example.com/existing",
                title="Existing Link",
                favicon="",
                status=ProcessingStatus.FINISHED,
                user_id=1,
            )
            session.add(link_a)
            await session.commit()

    asyncio.run(seed())

    app.dependency_overrides[current_active_user] = mock_auth_dependency
    app.dependency_overrides[get_async_session] = override_get_async_session

    with patch("backend.api.services.links.vector_store.remove_link_documents"), \
         patch("backend.api.services.links.queue_link", new_callable=AsyncMock):
        client = TestClient(app)
        yield client, tmp_path

    app.dependency_overrides.clear()


def test_submit_link_endpoint(client_env):
    client, _ = client_env
    headers = {"Authorization": "Bearer token_a"}

    res = client.post(
        "/links/submit",
        headers=headers,
        json={"url": "https://example.com/new-page"}
    )
    assert res.status_code == 202
    data = res.json()
    assert data["url"] == "https://example.com/new-page"
    assert data["status"] == "pending"
    assert data["id"] is not None


def test_submit_links_bulk_endpoint(client_env):
    client, _ = client_env
    headers = {"Authorization": "Bearer token_a"}

    res = client.post(
        "/links/bulk",
        headers=headers,
        json={"urls": ["https://example.com/page1", "https://example.com/page2"]}
    )
    assert res.status_code == 202
    data = res.json()
    assert data["links_added"] == 2


def test_list_links_endpoint(client_env):
    client, _ = client_env
    headers_a = {"Authorization": "Bearer token_a"}
    headers_b = {"Authorization": "Bearer token_b"}

    res_a = client.get("/links/?skip=0&limit=10", headers=headers_a)
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["total"] >= 1
    assert len(data_a["links"]) >= 1

    res_b = client.get("/links/?skip=0&limit=10", headers=headers_b)
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["total"] == 0
    assert len(data_b["links"]) == 0


def test_recursive_crawl_endpoint(client_env):
    client, _ = client_env
    headers = {"Authorization": "Bearer token_a"}

    with patch("backend.api.services.links.recursive_url_processing_queue.put", new_callable=AsyncMock) as mock_put:
        res = client.post(
            "/links/crawl",
            headers=headers,
            json={"url": "https://example.com/crawl-target"}
        )
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "submitted"
        assert data["url"] == "https://example.com/crawl-target"
        mock_put.assert_called_once()


def test_delete_link_endpoint(client_env):
    client, _ = client_env
    headers_a = {"Authorization": "Bearer token_a"}
    headers_b = {"Authorization": "Bearer token_b"}

    # User B cannot delete User A's link -> 404
    res_b = client.delete("/links/1", headers=headers_b)
    assert res_b.status_code == 404

    # User A deletes their link -> 200
    res_a = client.delete("/links/1", headers=headers_a)
    assert res_a.status_code == 200
    assert res_a.json()["status"] == "deleted"

    # Subsequent deletion -> 404
    res_a_again = client.delete("/links/1", headers=headers_a)
    assert res_a_again.status_code == 404
