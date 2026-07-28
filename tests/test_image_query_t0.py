import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from backend.main import app
from backend.core.image_ingest import ImageExtractionError
from backend.api.dependencies import current_active_user
from backend.api.models import User

client = TestClient(app)


async def override_current_user():
    return User(id=1, email="test@test.com")


def _ok_gate(*_a, **_k):
    return True, "OK"


def test_unauthorized():
    # Ensure no override for this test
    app.dependency_overrides = {}
    with open(__file__, "rb") as f:
        res = client.post("/documents/search/by-image", files={"file": ("test.png", f, "image/png")})
        assert res.status_code == 401

        res = client.post("/chat/by-image", files={"file": ("test.png", f, "image/png")})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_search_by_image_success():
    app.dependency_overrides[current_active_user] = override_current_user
    try:
        with patch("backend.core.image_query_gate.validate_image_query_upload", side_effect=_ok_gate), \
             patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract, \
             patch("backend.api.routers.documents.search_service.search_documents", new_callable=AsyncMock) as mock_search, \
             patch("backend.api.routers.documents.search_service.format_search_hits") as mock_format:

            mock_extract.return_value = "extracted text from image"
            mock_search.return_value = []
            mock_format.return_value = ([], [])

            with open(__file__, "rb") as f:
                res = client.post("/documents/search/by-image", files={"file": ("test.png", f, "image/png")})

            assert res.status_code == 200
            assert res.json() == {"documents": [], "count": 0}
            mock_extract.assert_called_once()
            mock_search.assert_called_once()
            assert mock_search.call_args[1]["prompt"] == "extracted text from image"
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_search_by_image_alias_path():
    app.dependency_overrides[current_active_user] = override_current_user
    try:
        with patch("backend.core.image_query_gate.validate_image_query_upload", side_effect=_ok_gate), \
             patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract, \
             patch("backend.api.routers.documents.search_service.search_documents", new_callable=AsyncMock) as mock_search, \
             patch("backend.api.routers.documents.search_service.format_search_hits") as mock_format:

            mock_extract.return_value = "alias path text"
            mock_search.return_value = []
            mock_format.return_value = ([], [])

            with open(__file__, "rb") as f:
                res = client.post("/documents/search-by-image", files={"file": ("shot.jpg", f, "image/jpeg")})

            assert res.status_code == 200
            assert res.json()["count"] == 0
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_search_by_image_bad_extension():
    app.dependency_overrides[current_active_user] = override_current_user
    try:
        with open(__file__, "rb") as f:
            res = client.post("/documents/search/by-image", files={"file": ("x.gif", f, "image/gif")})
        assert res.status_code == 400
        assert "Unsupported image type" in res.json()["detail"]
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_search_by_image_gate_blocked():
    app.dependency_overrides[current_active_user] = override_current_user
    try:
        with patch(
            "backend.core.image_query_gate.image_ingest_allowed",
            return_value=(False, "Neither OCR nor Gemini captioning is available"),
        ):
            with open(__file__, "rb") as f:
                res = client.post("/documents/search/by-image", files={"file": ("test.png", f, "image/png")})
            assert res.status_code == 400
            assert "no extraction backend" in res.json()["detail"]
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_search_by_image_extract_fail():
    app.dependency_overrides[current_active_user] = override_current_user
    try:
        with patch("backend.core.image_query_gate.validate_image_query_upload", side_effect=_ok_gate), \
             patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract:
            mock_extract.side_effect = ImageExtractionError("neither OCR nor Gemini yielded text")

            with open(__file__, "rb") as f:
                res = client.post("/documents/search/by-image", files={"file": ("test.png", f, "image/png")})

            assert res.status_code == 400
            assert "neither OCR" in res.json()["detail"]
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_chat_by_image_success():
    app.dependency_overrides[current_active_user] = override_current_user
    try:
        with patch("backend.core.image_query_gate.validate_image_query_upload", side_effect=_ok_gate), \
             patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract, \
             patch("backend.api.routers.chat.chat_service.rag_chat_events") as mock_chat:

            mock_extract.return_value = "chat extracted text"

            async def dummy_events(*args, **kwargs):
                yield {"type": "done"}

            mock_chat.side_effect = dummy_events

            with open(__file__, "rb") as f:
                res = client.post("/chat/by-image", files={"file": ("test.png", f, "image/png")})

            assert res.status_code == 200
            assert "done" in res.text
            mock_extract.assert_called_once()
            mock_chat.assert_called_once()
            assert mock_chat.call_args[1]["question"] == "chat extracted text"
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_chat_by_image_extract_fail():
    app.dependency_overrides[current_active_user] = override_current_user
    try:
        with patch("backend.core.image_query_gate.validate_image_query_upload", side_effect=_ok_gate), \
             patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract:
            mock_extract.side_effect = ImageExtractionError("extract fail")

            with open(__file__, "rb") as f:
                res = client.post("/chat/by-image", files={"file": ("test.png", f, "image/png")})

            assert res.status_code == 400
            assert "extract fail" in res.json()["detail"]
    finally:
        app.dependency_overrides = {}
