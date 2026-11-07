import io
import os
import pytest
from PIL import Image, ImageDraw
from backend.core.visual_assets import (
    VisualAssetStore,
    compress_and_standardize_image,
    VisualEvidence,
)
from backend.api.services.chat import rag_chat_events


def test_compress_and_standardize_rgba():
    """Verify RGBA image is converted to clean RGB JPEG <= 1280px."""
    img = Image.new("RGBA", (2000, 1000), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_rgba = buf.getvalue()

    compressed = compress_and_standardize_image(raw_rgba, max_dimension=1280)
    assert len(compressed) > 0
    with Image.open(io.BytesIO(compressed)) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"
        assert max(out_img.size) <= 1280
        assert out_img.size == (1280, 640)


def test_visual_asset_store_save_and_resolve(tmp_path, monkeypatch):
    """Verify VisualAssetStore saves asset and resolve_hit_images picks it up."""
    monkeypatch.setattr("backend.config.settings.UPLOAD_DIR", str(tmp_path))

    # 1. Save an image asset
    test_img = Image.new("RGB", (100, 100), color=(0, 255, 0))
    buf = io.BytesIO()
    test_img.save(buf, format="JPEG")
    saved_path = VisualAssetStore.save_visual_asset(
        resource_id="doc_999",
        filename="figure_1.jpg",
        image_bytes=buf.getvalue(),
    )
    assert os.path.exists(saved_path)
    assert "mm_assets/doc_999" in saved_path

    # 2. Mock search hits containing image_path
    class DummyDoc:
        def __init__(self, metadata, content="Chart showing trend"):
            self.metadata = metadata
            self.page_content = content

    hits = [
        (DummyDoc({"image_path": saved_path, "resource_id": "doc_999"}), 0.12, "source_1"),
        (DummyDoc({"filename": "notes.md"}), 0.35, "source_2"),
    ]

    evidences = VisualAssetStore.resolve_hit_images(hits, max_images=3)
    assert len(evidences) == 1
    assert evidences[0].image_path == saved_path
    assert evidences[0].hit_index == 1
    assert len(evidences[0].image_bytes) > 0


@pytest.mark.asyncio
async def test_rag_chat_events_citations_has_image(monkeypatch):
    """Verify citations emit has_image=True when image_path is present."""
    class DummyDoc:
        def __init__(self):
            self.metadata = {
                "id": "c1",
                "filename": "chart.png",
                "image_path": "/tmp/dummy.jpg",
                "page": "1",
                "source_type": "file",
            }
            self.page_content = "Quarterly revenue report"

    async def mock_search(*args, **kwargs):
        return [DummyDoc()]

    monkeypatch.setattr("backend.api.services.search.search_documents", mock_search)
    monkeypatch.setattr("backend.api.services.search.format_search_hits", lambda docs, **kw: ([(docs[0], 0.1, "file")], ["file"]))

    # Mock stream generator to avoid external API calls during unit test
    async def mock_stream(*args, **kwargs):
        images = kwargs.get("images") or []
        assert isinstance(images, list)
        yield "The chart indicates positive growth."

    monkeypatch.setattr("backend.api.services.chat.stream_openai_chat", mock_stream)

    events = []
    async for ev in rag_chat_events(
        question="What is the revenue?",
        user_email="test@example.com",
        user_id=1,
        use_rag=True,
    ):
        events.append(ev)

    cit_ev = next(e for e in events if e.get("type") == "citations")
    citations = cit_ev.get("citations", [])
    assert len(citations) == 1
    assert citations[0]["has_image"] is True
    assert citations[0]["image_path"] == "/tmp/dummy.jpg"

    token_ev = next(e for e in events if e.get("type") == "token")
    assert "positive growth" in token_ev.get("content")
