import io
import pytest
from PIL import Image
from langchain.schema import Document

from backend.config import settings
from backend.vector_store.lance_db import (
    add_visual_documents,
    fetch_visual_documents,
    remove_visual_documents,
    db,
    VISUAL_TABLE_NAME,
)


def _make_colored_image_bytes(color: tuple) -> bytes:
    img = Image.new("RGB", (64, 64), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def mock_visual_embedder(monkeypatch):
    """
    Mock get_visual_embedder to generate deterministic vectors based on color/text
    so unit tests run in milliseconds without hitting network quotas.
    """
    class MockEmbedder:
        def __init__(self):
            self.dimension = int(getattr(settings, "VISUAL_EMBEDDING_DIMENSION", 768))

        def embed_image(self, image_bytes: bytes):
            with Image.open(io.BytesIO(image_bytes)) as im:
                r, g, b = im.getpixel((0, 0))
            # Put color values into first 3 dimensions
            vec = [0.0] * self.dimension
            vec[0] = float(r) / 255.0
            vec[1] = float(g) / 255.0
            vec[2] = float(b) / 255.0
            return vec

        def embed_images(self, image_bytes_list):
            return [self.embed_image(b) for b in image_bytes_list]

        def embed_query_text(self, text: str):
            vec = [0.0] * self.dimension
            lower = text.lower()
            if "red" in lower:
                vec[0] = 1.0
            elif "green" in lower:
                vec[1] = 1.0
            elif "blue" in lower:
                vec[2] = 1.0
            return vec

        def embed_visual_query(self, text=None, image_bytes=None):
            if image_bytes:
                return self.embed_image(image_bytes)
            if text:
                return self.embed_query_text(text)
            return [0.0] * self.dimension

    mock_inst = MockEmbedder()
    monkeypatch.setattr("backend.core.visual_embedder.get_visual_embedder", lambda: mock_inst)
    return mock_inst


def test_l2_visual_store_lifecycle(mock_visual_embedder):
    """Verify add, search by image, cross-modal search by text, and tenant isolation."""
    red_img = _make_colored_image_bytes((255, 0, 0))
    green_img = _make_colored_image_bytes((0, 255, 0))

    doc_red = Document(
        page_content="Red geometric banner",
        metadata={
            "id": "vis_red_1",
            "filename": "red_banner.jpg",
            "belongs_to": "alice@example.com",
            "user_id": "101",
            "resource_id": "res_red",
            "source_type": "file",
            "image_path": "/tmp/red.jpg",
        }
    )

    doc_green = Document(
        page_content="Green organic forest graph",
        metadata={
            "id": "vis_green_1",
            "filename": "green_forest.jpg",
            "belongs_to": "bob@example.com",
            "user_id": "102",
            "resource_id": "res_green",
            "source_type": "file",
            "image_path": "/tmp/green.jpg",
        }
    )

    # 1. Ingest both visual documents
    add_visual_documents([doc_red, doc_green], [red_img, green_img])

    # 2. Image-to-Image Search (Alice queries with a red image)
    query_red_img = _make_colored_image_bytes((240, 10, 10))
    hits_alice = fetch_visual_documents(
        image_bytes=query_red_img,
        window_size=5,
        username="alice@example.com",
        user_id=101,
    )
    assert len(hits_alice) >= 1
    top_doc, dist, _src = hits_alice[0]
    assert top_doc.metadata["id"] == "vis_red_1"
    assert top_doc.metadata["user_id"] == "101"

    # 3. Tenant Isolation Guard: Alice must NOT see Bob's green image even if searching for green
    hits_alice_green = fetch_visual_documents(
        prompt="green forest",
        window_size=5,
        username="alice@example.com",
        user_id=101,
    )
    # Alice should see 0 green hits because it belongs to Bob (user_id=102)
    for d, _dist, _ in hits_alice_green:
        assert d.metadata.get("user_id") != "102"
        assert d.metadata.get("belongs_to") != "bob@example.com"

    # 4. Cross-Modal Text-to-Image Search (Bob searches for "green")
    hits_bob_green = fetch_visual_documents(
        prompt="lush green trees",
        window_size=5,
        username="bob@example.com",
        user_id=102,
    )
    assert len(hits_bob_green) >= 1
    assert hits_bob_green[0][0].metadata["id"] == "vis_green_1"

    # 5. Clean up / Deletion verification
    removed = remove_visual_documents(resource_id="res_red", username="alice@example.com", user_id=101)
    assert removed is True

    hits_alice_after = fetch_visual_documents(
        image_bytes=query_red_img,
        window_size=5,
        username="alice@example.com",
        user_id=101,
    )
    assert not any(d.metadata.get("id") == "vis_red_1" for d, _, _ in hits_alice_after)


def test_siglip2_onnx_real_embedder():
    """Verify local SigLIP 2 Base ONNX embedder without mocks."""
    from backend.core.visual_embedder import VisualEmbedder
    embedder = VisualEmbedder()
    assert embedder.dimension == 768
    assert embedder.provider == "siglip2_onnx"

    # 1. Embed real image bytes
    test_img = _make_colored_image_bytes((120, 180, 240))
    vec = embedder.embed_image(test_img)
    assert len(vec) == 768
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-3

    # 2. Embed real query text
    t_vec = embedder.embed_query_text("blue geometric pattern")
    assert len(t_vec) == 768
    t_norm = sum(x * x for x in t_vec) ** 0.5
    assert abs(t_norm - 1.0) < 1e-3

