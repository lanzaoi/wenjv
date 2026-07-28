import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from backend.main import app
from backend.api.dependencies import current_active_user
from backend.api.models import User
from backend.core.image_ingest import ImageExtractionError

client = TestClient(app)

USER_A = User(id=1, email="10000@qq.com", username="user_a", is_active=True, is_superuser=False)
USER_B = User(id=2, email="other@test.com", username="user_b", is_active=True, is_superuser=False)

async def override_current_user_A():
    return USER_A

async def override_current_user_B():
    return USER_B

# --- T3-01: API Boundary tests for Upload ---
def test_upload_unauthorized():
    app.dependency_overrides = {}
    with open(__file__, "rb") as f:
        res = client.post("/file/upload", files={"file": ("test.png", f, "image/png")})
    assert res.status_code == 401

def test_upload_image_ingest_disabled():
    app.dependency_overrides[current_active_user] = override_current_user_A
    try:
        with patch("backend.core.image_ingest_gate.image_ingest_allowed") as mock_allowed, \
             patch("backend.api.routers.files.is_allowed_upload_filename") as mock_is_allowed:
            mock_is_allowed.return_value = True
            mock_allowed.return_value = (False, "IMAGE_INGEST_ENABLED is False")
            
            with open(__file__, "rb") as f:
                res = client.post("/file/upload", files={"file": ("test.png", f, "image/png")})
                
            assert res.status_code == 400
            assert "IMAGE_INGEST_ENABLED is False" in res.json()["detail"]
    finally:
        app.dependency_overrides = {}

def test_upload_unsupported_extension():
    app.dependency_overrides[current_active_user] = override_current_user_A
    try:
        with patch("backend.core.image_ingest_gate.image_ingest_allowed") as mock_allowed:
            mock_allowed.return_value = (True, "OK")
            
            with open(__file__, "rb") as f:
                res = client.post("/file/upload", files={"file": ("test.gif", f, "image/gif")})
                
            assert res.status_code == 400
            assert "not allowed" in res.json()["detail"].lower()
    finally:
        app.dependency_overrides = {}

# --- T3-02: Image Isolation ---
@pytest.mark.asyncio
async def test_image_search_isolation():
    # User B searches via /search/by-image
    # We mock search_documents to simulate backend Vector DB layer isolation
    # We will verify that search_documents is called with user_id=USER_B.id
    
    app.dependency_overrides[current_active_user] = override_current_user_B
    try:
        with patch(
                "backend.core.image_query_gate.validate_image_query_upload",
                return_value=(True, "OK"),
            ), \
             patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract, \
             patch("backend.api.routers.documents.search_service.search_documents", new_callable=AsyncMock) as mock_search, \
             patch("backend.api.routers.documents.search_service.format_search_hits") as mock_format:

            mock_extract.return_value = "extracted text from image B"
            mock_search.return_value = []
            mock_format.return_value = ([], [])

            with open(__file__, "rb") as f:
                res = client.post("/documents/search/by-image", files={"file": ("test.png", f, "image/png")})

            assert res.status_code == 200

            # Verify the backend isolation logic is respected by checking the passed user_id
            mock_search.assert_called_once()
            called_kwargs = mock_search.call_args[1]
            assert called_kwargs["user_id"] == USER_B.id
            assert called_kwargs["user_email"] == USER_B.email
            assert called_kwargs["prompt"] == "extracted text from image B"
    finally:
        app.dependency_overrides = {}
