import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.dependencies import current_active_user
from backend.api.models import User
from backend.api.services.chat import rag_chat_events
from backend.api.services.search import _compute_query_hash


def test_query_hash_includes_image_bytes():
    """Verify query hash differs when query_image_bytes differs."""
    h1 = _compute_query_hash(
        prompt="Explain this diagram",
        include_sources=None,
        exclude_sources=None,
        source_type=None,
        window_size=5,
        query_image_bytes=b"image_bytes_A",
    )
    h2 = _compute_query_hash(
        prompt="Explain this diagram",
        include_sources=None,
        exclude_sources=None,
        source_type=None,
        window_size=5,
        query_image_bytes=b"image_bytes_B",
    )
    h_none = _compute_query_hash(
        prompt="Explain this diagram",
        include_sources=None,
        exclude_sources=None,
        source_type=None,
        window_size=5,
        query_image_bytes=None,
    )
    assert h1 != h2
    assert h1 != h_none


@pytest.mark.asyncio
async def test_rag_refuse_bypassed_when_image_present(monkeypatch):
    """
    Verify that when use_rag=True, hits=[], but a query image is provided,
    the model does NOT refuse with '抱歉，知识库中未找到相关依据'.
    Instead, it proceeds to VLM generation!
    """
    async def mock_empty_search(*args, **kwargs):
        return []

    monkeypatch.setattr("backend.api.services.search.search_documents", mock_empty_search)
    monkeypatch.setattr("backend.api.services.search.format_search_hits", lambda docs, **kw: ([], []))

    streamed_tokens = []
    async def mock_stream(*args, **kwargs):
        images = kwargs.get("images") or []
        assert len(images) > 0, "Expected images to be passed to VLM!"
        yield "This image shows a flowchart."

    monkeypatch.setattr("backend.api.services.chat.stream_openai_chat", mock_stream)

    # 1. Create a dummy image
    test_img = Image.new("RGB", (100, 100), color=(100, 150, 200))
    buf = io.BytesIO()
    test_img.save(buf, format="JPEG")
    raw_img = buf.getvalue()

    events = []
    async for ev in rag_chat_events(
        question="What is this?",
        user_email="test@example.com",
        user_id=1,
        use_rag=True,
        query_image_bytes=raw_img,
    ):
        events.append(ev)

    # Verify no refusal token
    tokens = [e.get("content", "") for e in events if e.get("type") == "token"]
    full_resp = "".join(tokens)
    assert "抱歉，知识库中未找到相关依据" not in full_resp
    assert "This image shows a flowchart." in full_resp


def test_chat_attachment_upload_and_resolution(tmp_path, monkeypatch):
    """Verify POST /chat/attachments uploads image and can be resolved by identifier."""
    monkeypatch.setattr("backend.config.settings.UPLOAD_DIR", str(tmp_path))

    dummy_user = User(
        id=999,
        email="attach_test@wenjv.internal",
        hashed_password="pw",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    app.dependency_overrides[current_active_user] = lambda: dummy_user

    client = TestClient(app)

    # Create dummy image
    test_img = Image.new("RGB", (200, 200), color=(255, 0, 128))
    buf = io.BytesIO()
    test_img.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    res = client.post(
        "/chat/attachments",
        files={"file": ("screenshot.png", raw_bytes, "image/png")},
        data={"session_id": "test_sess_123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "media_url" in data
    media_url = data["media_url"]
    assert "mm_assets/sessions/999/test_sess_123" in media_url

    # Now verify VisualAssetStore can resolve it
    from backend.core.visual_assets import VisualAssetStore
    resolved = VisualAssetStore.resolve_image_from_identifier(media_url)
    assert resolved is not None
    resolved_bytes, mime = resolved
    assert len(resolved_bytes) > 0
    assert mime == "image/jpeg"

    app.dependency_overrides.clear()
