import pytest
from backend.config import Settings

def test_ocr_mode_off_whitelist():
    s = Settings(OCR_MODE="off")
    assert "png" not in s.ALLOWED_UPLOAD_EXTENSIONS
    assert "jpg" not in s.ALLOWED_UPLOAD_EXTENSIONS
    assert "pdf" in s.ALLOWED_UPLOAD_EXTENSIONS

def test_ocr_mode_auto_whitelist():
    s = Settings(OCR_MODE="auto")
    assert "png" in s.ALLOWED_UPLOAD_EXTENSIONS
    assert "jpg" in s.ALLOWED_UPLOAD_EXTENSIONS
    assert "jpeg" in s.ALLOWED_UPLOAD_EXTENSIONS
    assert "pdf" in s.ALLOWED_UPLOAD_EXTENSIONS

def test_ocr_mode_always_whitelist():
    s = Settings(OCR_MODE="always")
    assert "png" in s.ALLOWED_UPLOAD_EXTENSIONS
    assert "jpeg" in s.ALLOWED_UPLOAD_EXTENSIONS
