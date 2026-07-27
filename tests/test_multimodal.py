"""Tests for backend.core.multimodal."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from backend.core.multimodal import (
    extract_images_from_pdf, generate_caption, table_to_markdown,
    extract_tables_from_pdf, extract_tables_from_image,
    process_pdf_images, process_pdf_tables, process_pdf_multimodal,
)
from backend.config import settings


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-123")
    monkeypatch.setattr(settings, "MULTIMODAL_ENABLED", True)
    monkeypatch.setattr(settings, "GEMINI_VL_MODEL", "gemini-2.0-flash")


def test_table_to_markdown():
    table = [["列名 1", "列名 2"], ["数据 A", "数据 B"], ["", "数据 C"]]
    md = table_to_markdown(table)
    assert "| 列名 1 | 列名 2 |" in md
    assert "| --- | --- |" in md
    assert "| 数据 A | 数据 B |" in md
    assert table_to_markdown([]) == ""
    assert table_to_markdown([["", ""]]) == ""


@pytest.mark.asyncio
async def test_process_pdf_multimodal_integration(mock_settings):
    """Integration: PDF with 1 image → caption + no table."""
    with patch("backend.core.multimodal.extract_images_from_pdf", return_value=[b"img"]), \
         patch("backend.core.multimodal.generate_caption", return_value="一张图"), \
         patch("backend.core.multimodal.extract_tables_from_image", return_value=""), \
         patch("backend.vector_store.lance_db.add_documents") as mock_add:
        n = await process_pdf_multimodal("test.pdf", "doc1", "user@test.com", 1)
        assert n == 1  # one caption, no table
        mock_add.assert_called_once()
        docs = mock_add.call_args[0][0]
        assert docs[0].metadata["source_type"] == "image_caption"

def test_extract_images_from_pdf_mock():
    """Mock pypdfium2: PdfDocument → page.render → PIL → PNG bytes."""
    with patch("pypdfium2.PdfDocument") as mock_pdf_cls:
        mock_bitmap = MagicMock()
        mock_rgb = MagicMock()
        def _save(buf, format=None):
            buf.write(b"fake-png")
        mock_rgb.save = _save
        mock_pil = MagicMock()
        mock_pil.convert.return_value = mock_rgb
        mock_bitmap.to_pil.return_value = mock_pil
        mock_page = MagicMock()
        mock_page.render.return_value = mock_bitmap
        mock_pdf = MagicMock()
        mock_pdf.__len__.return_value = 1
        mock_pdf.__getitem__.return_value = mock_page
        mock_pdf_cls.return_value = mock_pdf

        images = extract_images_from_pdf("dummy.pdf")
        assert len(images) == 1
        assert images[0] == b"fake-png"


@pytest.mark.asyncio
async def test_generate_caption_mock(mock_settings):
    with patch("google.generativeai.configure") as mock_conf, \
         patch("google.generativeai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "这是一张包含文字和表格的图片。"
        mock_model.generate_content = MagicMock(return_value=mock_resp)
        mock_model_cls.return_value = mock_model

        caption = await generate_caption(b"dummy-image")
        assert "这是一张" in caption
        mock_conf.assert_called_once_with(api_key="test-key-123")


@pytest.mark.asyncio
async def test_generate_caption_fail_open(mock_settings):
    with patch("google.generativeai.configure"), \
         patch("google.generativeai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content = MagicMock(side_effect=Exception("API Timeout"))
        mock_model_cls.return_value = mock_model
        caption = await generate_caption(b"dummy-image")
        assert caption == ""


@pytest.mark.asyncio
async def test_extract_tables_from_image_mock(mock_settings):
    with patch("google.generativeai.configure"), \
         patch("google.generativeai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "| 姓名 | 年龄 |\n| --- | --- |\n| 张三 | 28 |"
        mock_model.generate_content = MagicMock(return_value=mock_resp)
        mock_model_cls.return_value = mock_model

        md = await extract_tables_from_image(b"fake-page")
        assert "| 姓名 | 年龄 |" in md


@pytest.mark.asyncio
async def test_extract_tables_from_image_no_table(mock_settings):
    with patch("google.generativeai.configure"), \
         patch("google.generativeai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "无表格"
        mock_model.generate_content = MagicMock(return_value=mock_resp)
        mock_model_cls.return_value = mock_model

        md = await extract_tables_from_image(b"fake-page")
        assert md == ""


@pytest.mark.asyncio
async def test_process_pdf_images_flow(mock_settings):
    with patch("backend.core.multimodal.extract_images_from_pdf", return_value=[b"i1", b"i2"]), \
         patch("backend.core.multimodal.generate_caption", side_effect=["描述一", "描述二"]):
        docs = await process_pdf_images("test.pdf", resource_id="res-100")
        assert len(docs) == 2
        assert docs[0].page_content == "描述一"
        assert docs[0].metadata["source_type"] == "image_caption"
        assert docs[1].page_content == "描述二"


@pytest.mark.asyncio
async def test_process_pdf_tables_flow(mock_settings):
    with patch("backend.core.multimodal.extract_tables_from_pdf", AsyncMock(
        return_value=["| 产品 | 价格 |\n| --- | --- |\n| 苹果 | 5元 |"])):
        docs = await process_pdf_tables("test.pdf", resource_id="res-200")
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "table"
        assert docs[0].metadata["resource_id"] == "res-200"


@pytest.mark.asyncio
async def test_process_pdf_tables_fail_open():
    with patch("backend.core.multimodal.extract_tables_from_pdf", AsyncMock(side_effect=Exception("Crash"))):
        docs = await process_pdf_tables("test.pdf")
        assert docs == []


