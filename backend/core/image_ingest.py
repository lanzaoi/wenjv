import logging
from typing import Optional
from backend.config import settings
from backend.core.ocr_client import ocr_image_bytes

logger = logging.getLogger(__name__)

class ImageExtractionError(Exception):
    """Raised when an image yields no text from OCR or Captioning."""
    pass

async def extract_text_from_image_bytes(data: bytes, filename: Optional[str] = None) -> str:
    """
    Extracts text from image bytes following the I2 rules:
    1. OCR
    2. If text, return '[OCR] ...'
    3. If no text and fallback enabled, call generate_caption (or Gemini)
    4. If text, return '[Gemini] ...'
    5. If still empty, raise ImageExtractionError
    """
    ocr_text = ""
    try:
        raw_ocr = await ocr_image_bytes(data)
        if raw_ocr and raw_ocr.strip():
            ocr_text = raw_ocr.strip()
    except Exception as e:
        logger.warning(f"OCR extraction failed for {filename or 'image'}: {e}")
        
    if ocr_text:
        return f"[OCR] {ocr_text}"
        
    caption_text = ""
    if getattr(settings, "IMAGE_CAPTION_FALLBACK_ENABLED", True):
        try:
            # Directly invoke _gemini_caption since OCR has already been attempted above.
            from backend.core.multimodal import _gemini_caption
            raw_caption = await _gemini_caption(data, settings, settings.GEMINI_VL_MODEL)
            if raw_caption and raw_caption.strip():
                caption_text = raw_caption.strip()
        except Exception as e:
            logger.warning(f"Caption extraction failed for {filename or 'image'}: {e}")
            
    if caption_text:
        return f"[Gemini] {caption_text}"
        
    raise ImageExtractionError(f"Image ingestion failed for {filename or 'image'}: neither OCR nor Gemini yielded text.")
