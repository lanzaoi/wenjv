from typing import Tuple

def is_ocr_available(settings) -> bool:
    if getattr(settings, "OCR_MODE", "off") == "off":
        return False
    if getattr(settings, "OCR_PROVIDER", "") == "aistudio":
        return bool(getattr(settings, "OCR_AISTUDIO_ACCESS_TOKEN", "").strip())
    return True

def is_caption_available(settings) -> bool:
    if not getattr(settings, "IMAGE_CAPTION_FALLBACK_ENABLED", True):
        return False
    # Settings validator maps GOOGLE_API_KEY → GEMINI_API_KEY; check both for mocks/raw env.
    key = (
        getattr(settings, "GEMINI_API_KEY", "")
        or getattr(settings, "GOOGLE_API_KEY", "")
        or ""
    )
    return bool(str(key).strip())

def image_ingest_allowed(settings) -> Tuple[bool, str]:
    """
    Check if image ingestion is allowed based on E3 rules.
    Returns (is_allowed, reason_if_not)
    """
    if not getattr(settings, "IMAGE_INGEST_ENABLED", True):
        return False, "IMAGE_INGEST_ENABLED is False"
        
    ocr_ok = is_ocr_available(settings)
    caption_ok = is_caption_available(settings)
    
    if not ocr_ok and not caption_ok:
        return False, "Neither OCR nor Gemini captioning is available"
        
    return True, "OK"
