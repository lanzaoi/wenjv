import pytest
import asyncio
from unittest.mock import patch
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.api.dependencies import current_active_user
from backend.database import get_async_session, Base
from backend.api.models import User, Note, IngestionJob, JobStatus, ProcessingStatus

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
def setup_job_retry_env(tmp_path):
    db_path = tmp_path / "test_retry.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    
    from sqlalchemy import create_engine
    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    async_engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    async_session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_async_session():
        async with async_session_maker() as session:
            yield session

    async def seed_data():
        async with async_session_maker() as session:
            # Note 1 for failed job
            note_failed = Note(
                id=10, filename="failed.md", title="Failed Note",
                user_id=1, file_path="failed.md", status=ProcessingStatus.FAILED,
                error_message="some error"
            )
            # Job 101: FAILED owned by A
            job_failed = IngestionJob(
                id=101, job_type="note", resource_id=10, user_id=1, user_email="10000@qq.com",
                status=JobStatus.FAILED, attempts=3, max_attempts=3, last_error="some error"
            )
            
            # Job 102: SUCCEEDED owned by A
            job_succeeded = IngestionJob(
                id=102, job_type="note", resource_id=10, user_id=1, user_email="10000@qq.com",
                status=JobStatus.SUCCEEDED, attempts=1, max_attempts=3, last_error=None
            )
            
            # Job 103: CANCELLED owned by A
            job_cancelled = IngestionJob(
                id=103, job_type="note", resource_id=10, user_id=1, user_email="10000@qq.com",
                status=JobStatus.CANCELLED, attempts=1, max_attempts=3, last_error="user cancelled"
            )

            session.add_all([note_failed, job_failed, job_succeeded, job_cancelled])
            await session.commit()

    asyncio.run(seed_data())

    app.dependency_overrides[current_active_user] = mock_auth_dependency
    app.dependency_overrides[get_async_session] = override_get_async_session

    with patch("backend.api.services.jobs.notify_workers") as mock_notify:
        yield mock_notify

    app.dependency_overrides.clear()


def test_job_retry_endpoint(setup_job_retry_env):
    mock_notify = setup_job_retry_env
    client = TestClient(app)
    headers_a = {"Authorization": "Bearer token_a"}
    headers_b = {"Authorization": "Bearer token_b"}

    # 1. Unauthenticated retry -> 401
    res1 = client.post("/jobs/101/retry")
    assert res1.status_code == 401

    # 2. B user retry A's job -> 404
    res2 = client.post("/jobs/101/retry", headers=headers_b)
    assert res2.status_code == 404

    # 3. Succeeded job retry -> 409
    res3 = client.post("/jobs/102/retry", headers=headers_a)
    assert res3.status_code == 409
    assert "Cannot retry job in status" in res3.json()["detail"]

    # 4. A user retry FAILED job -> 200, status becomes pending, error cleared
    res4 = client.post("/jobs/101/retry", headers=headers_a)
    assert res4.status_code == 200
    data4 = res4.json()
    assert data4["job_id"] == 101
    assert data4["status"] == "pending"
    mock_notify.assert_called()

    # Verify via GET /jobs/101 that it is pending and error cleared
    res_get = client.get("/jobs/101", headers=headers_a)
    assert res_get.status_code == 200
    job_data = res_get.json()
    assert job_data["status"] == "pending"
    assert job_data["attempts"] == 0
    assert job_data["last_error"] is None

    # 5. A user retry CANCELLED job -> 200
    res5 = client.post("/jobs/103/retry", headers=headers_a)
    assert res5.status_code == 200
    assert res5.json()["status"] == "pending"
