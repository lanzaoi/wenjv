import pytest
from unittest.mock import MagicMock
from backend.core.image_ingest_gate import image_ingest_allowed

@pytest.fixture
def mock_settings():
    settings = MagicMock()
    # Default state for tests
    settings.IMAGE_INGEST_ENABLED = True
    settings.IMAGE_CAPTION_FALLBACK_ENABLED = True
    settings.OCR_MODE = "off"
    settings.OCR_PROVIDER = "aistudio"
    settings.OCR_AISTUDIO_ACCESS_TOKEN = ""
    settings.GEMINI_API_KEY = ""
    settings.GOOGLE_API_KEY = ""
    return settings

def test_image_ingest_disabled(mock_settings):
    mock_settings.IMAGE_INGEST_ENABLED = False
    mock_settings.GEMINI_API_KEY = "test_key" # even if gemini is ok
    
    allowed, reason = image_ingest_allowed(mock_settings)
    assert not allowed
    assert "IMAGE_INGEST_ENABLED is False" in reason

def test_image_ingest_no_ocr_no_gemini(mock_settings):
    mock_settings.IMAGE_INGEST_ENABLED = True
    mock_settings.OCR_MODE = "off"
    mock_settings.GEMINI_API_KEY = ""
    
    allowed, reason = image_ingest_allowed(mock_settings)
    assert not allowed
    assert "Neither OCR nor Gemini" in reason

def test_image_ingest_ocr_available(mock_settings):
    mock_settings.IMAGE_INGEST_ENABLED = True
    mock_settings.OCR_MODE = "on"
    mock_settings.OCR_PROVIDER = "aistudio"
    mock_settings.OCR_AISTUDIO_ACCESS_TOKEN = "token123"
    mock_settings.GEMINI_API_KEY = ""
    
    allowed, reason = image_ingest_allowed(mock_settings)
    assert allowed
    assert reason == "OK"

def test_image_ingest_only_gemini_available(mock_settings):
    mock_settings.IMAGE_INGEST_ENABLED = True
    mock_settings.OCR_MODE = "off"
    mock_settings.GEMINI_API_KEY = "gemini_key_123"
    
    allowed, reason = image_ingest_allowed(mock_settings)
    assert allowed
    assert reason == "OK"

def test_image_ingest_caption_fallback_disabled(mock_settings):
    mock_settings.IMAGE_INGEST_ENABLED = True
    mock_settings.IMAGE_CAPTION_FALLBACK_ENABLED = False
    mock_settings.OCR_MODE = "off"
    mock_settings.GEMINI_API_KEY = "gemini_key_123" # Even though key is present, fallback is disabled
    
    allowed, reason = image_ingest_allowed(mock_settings)
    assert not allowed
    assert "Neither OCR nor Gemini" in reason
