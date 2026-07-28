import pytest
from unittest.mock import patch, MagicMock
from backend.core.image_ingest import extract_text_from_image_bytes, ImageExtractionError

@pytest.mark.asyncio
async def test_extract_text_ocr_success():
    with patch("backend.core.image_ingest.ocr_image_bytes") as mock_ocr:
        mock_ocr.return_value = "hello world"
        result = await extract_text_from_image_bytes(b"dummy")
        assert result == "[OCR] hello world"

@pytest.mark.asyncio
async def test_extract_text_ocr_fails_caption_success():
    with patch("backend.core.image_ingest.ocr_image_bytes") as mock_ocr, \
         patch("backend.core.multimodal._gemini_caption") as mock_caption, \
         patch("backend.core.image_ingest.settings") as mock_settings:
         
        mock_ocr.return_value = ""
        mock_caption.return_value = "A beautiful diagram"
        mock_settings.IMAGE_CAPTION_FALLBACK_ENABLED = True
        
        result = await extract_text_from_image_bytes(b"dummy")
        assert result == "[Gemini] A beautiful diagram"

@pytest.mark.asyncio
async def test_extract_text_both_fail():
    with patch("backend.core.image_ingest.ocr_image_bytes") as mock_ocr, \
         patch("backend.core.multimodal._gemini_caption") as mock_caption, \
         patch("backend.core.image_ingest.settings") as mock_settings:
         
        mock_ocr.return_value = "   \n "
        mock_caption.return_value = ""
        mock_settings.IMAGE_CAPTION_FALLBACK_ENABLED = True
        
        with pytest.raises(ImageExtractionError) as exc:
            await extract_text_from_image_bytes(b"dummy")
        assert "neither OCR nor Gemini yielded text" in str(exc.value)

@pytest.mark.asyncio
async def test_extract_text_fallback_disabled():
    with patch("backend.core.image_ingest.ocr_image_bytes") as mock_ocr, \
         patch("backend.core.multimodal._gemini_caption") as mock_caption, \
         patch("backend.core.image_ingest.settings") as mock_settings:
         
        mock_ocr.return_value = ""
        mock_settings.IMAGE_CAPTION_FALLBACK_ENABLED = False
        
        with pytest.raises(ImageExtractionError):
            await extract_text_from_image_bytes(b"dummy")
            
        mock_caption.assert_not_called()
