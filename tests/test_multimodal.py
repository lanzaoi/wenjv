"""Tests for backend.core.multimodal — OCR-first, Gemini fallback."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from backend.core.multimodal import (
    extract_images_from_pdf, generate_caption, table_to_markdown,
    extract_tables_from_image, extract_tables_from_pdf,
    process_pdf_images, process_pdf_tables, process_pdf_multimodal,
    _extract_markdown_tables,
)
from backend.config import settings


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-123")
    monkeypatch.setattr(settings, "MULTIMODAL_ENABLED", True)
    monkeypatch.setattr(settings, "GEMINI_VL_MODEL", "gemini-2.0-flash")
    monkeypatch.setattr(settings, "OCR_MODE", "always")


def test_table_to_markdown():
    table = [["列名 1", "列名 2"], ["数据 A", "数据 B"], ["", "数据 C"]]
    md = table_to_markdown(table)
    assert "| 列名 1 | 列名 2 |" in md
    assert "| --- | --- |" in md
    assert table_to_markdown([]) == ""
    assert table_to_markdown([["", ""]]) == ""


def test_extract_markdown_tables():
    text = "some text\n| A | B |\n| --- | --- |\n| 1 | 2 |\nmore text"
    tables = _extract_markdown_tables(text)
    assert len(tables) == 1
    assert "| A | B |" in tables[0]
    assert "| 1 | 2 |" in tables[0]


def test_extract_markdown_tables_no_table():
    assert _extract_markdown_tables("plain text no table") == []


def test_extract_images_from_pdf_mock():
    with patch("pypdfium2.PdfDocument") as mock_pdf_cls:
        mock_bitmap, mock_rgb = MagicMock(), MagicMock()
        def _save(buf, format=None): buf.write(b"fake-png")
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
async def test_generate_caption_ocr_first(mock_settings):
    """OCR returns text → use it, no Gemini call."""
    with patch("backend.core.multimodal._ocr_for_caption", AsyncMock(return_value="OCR extracted text here")), \
         patch("backend.core.multimodal._gemini_caption") as mock_gemini:
        caption = await generate_caption(b"dummy-image")
        assert "[OCR] OCR extracted text here" in caption
        mock_gemini.assert_not_called()


@pytest.mark.asyncio
async def test_generate_caption_ocr_fallback_to_gemini(mock_settings):
    """OCR fails → Gemini fallback."""
    with patch("backend.core.multimodal._ocr_for_caption", AsyncMock(return_value="")), \
         patch("backend.core.multimodal._gemini_caption", AsyncMock(return_value="Gemini description")):
        caption = await generate_caption(b"dummy-image")
        assert "[Gemini] Gemini description" == caption


@pytest.mark.asyncio
async def test_generate_caption_both_fail(mock_settings):
    """Both OCR and Gemini fail → empty."""
    with patch("backend.core.multimodal._ocr_for_caption", AsyncMock(return_value="")), \
         patch("backend.core.multimodal._gemini_caption", AsyncMock(return_value="")):
        caption = await generate_caption(b"dummy-image")
        assert caption == ""


@pytest.mark.asyncio
async def test_extract_tables_ocr_first(mock_settings):
    """OCR returns markdown table → parsed directly, no Gemini."""
    ocr_output = "前言\n| 姓名 | 年龄 |\n| --- | --- |\n| 张三 | 28 |\n尾注"
    mock_genai = MagicMock()
    with patch("backend.core.ocr_client.ocr_image_bytes", AsyncMock(return_value=ocr_output)), \
         patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        md = await extract_tables_from_image(b"fake-page")
        assert "| 姓名 | 年龄 |" in md
        mock_genai.GenerativeModel.assert_not_called()


@pytest.mark.asyncio
async def test_extract_tables_ocr_no_table_fallback(mock_settings):
    """OCR returns text with no table → Gemini fallback."""
    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "| 产品 | 价格 |\n| --- | --- |\n| 苹果 | 5元 |"
    mock_model.generate_content = MagicMock(return_value=mock_resp)
    mock_genai.GenerativeModel.return_value = mock_model

    with patch("backend.core.ocr_client.ocr_image_bytes", AsyncMock(return_value="just text")), \
         patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        md = await extract_tables_from_image(b"fake-page")
        assert "| 产品 | 价格 |" in md
        mock_genai.configure.assert_called_once()
        mock_genai.GenerativeModel.assert_called_once()


@pytest.mark.asyncio
async def test_process_pdf_images_flow(mock_settings):
    with patch("backend.core.multimodal.extract_images_from_pdf", return_value=[b"i1", b"i2"]), \
         patch("backend.core.multimodal.generate_caption", side_effect=["[OCR] 描述一", "[OCR] 描述二"]):
        docs = await process_pdf_images("test.pdf", resource_id="res-100")
        assert len(docs) == 2
        assert "[OCR] 描述一" in docs[0].page_content
        assert docs[0].metadata["source_type"] == "image_caption"


@pytest.mark.asyncio
async def test_process_pdf_tables_flow(mock_settings):
    with patch("backend.core.multimodal.extract_tables_from_pdf", AsyncMock(
        return_value=["| 产品 | 价格 |\n| --- | --- |\n| 苹果 | 5元 |"])):
        docs = await process_pdf_tables("test.pdf", resource_id="res-200")
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "table"


@pytest.mark.asyncio
async def test_process_pdf_tables_fail_open():
    with patch("backend.core.multimodal.extract_tables_from_pdf", AsyncMock(side_effect=Exception("Crash"))):
        docs = await process_pdf_tables("test.pdf")
        assert docs == []


@pytest.mark.asyncio
async def test_process_pdf_multimodal_integration(mock_settings):
    """Full flow: 1 image → OCR caption + no table."""
    with patch("backend.core.multimodal.extract_images_from_pdf", return_value=[b"img"]), \
         patch("backend.core.multimodal.generate_caption", return_value="[OCR] 一张图"), \
         patch("backend.core.multimodal.extract_tables_from_image", return_value=""), \
         patch("backend.vector_store.lance_db.add_documents") as mock_add:
        n = await process_pdf_multimodal("test.pdf", "doc1", "user@test.com", 1)
        assert n == 1
        mock_add.assert_called_once()
        docs = mock_add.call_args[0][0]
        assert docs[0].metadata["source_type"] == "image_caption"
