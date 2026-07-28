"""Optional OCR enrichment for image-heavy PPTX slides (fail-open)."""
from __future__ import annotations

from typing import List

from backend.config import settings
from backend.core.logging import get_logger
from backend.parsers.base import ParsedChunk
from backend.parsers.pptx_parser import extract_pptx_image_blobs

logger = get_logger()


async def enrich_pptx_chunks_with_ocr(
    file_path: str,
    existing_text_chars: int = 0,
    min_chars: int | None = None,
) -> List[ParsedChunk]:
    """
    When slide text is thin, OCR embedded pictures.
    Never raises to caller for OCR failures — returns [] on any problem.
    """
    if not getattr(settings, "PPTX_OCR_EMPTY_SLIDES", False) and not getattr(
        settings, "MULTIMODAL_ENABLED", False
    ):
        return []

    threshold = min_chars
    if threshold is None:
        threshold = int(getattr(settings, "OCR_MIN_CHARS", 40) or 40)
    if existing_text_chars >= threshold:
        return []

    try:
        from backend.core.ocr_client import ocr_image_bytes
    except Exception as e:
        logger.warning(f"pptx OCR unavailable: {e}")
        return []

    try:
        blobs = extract_pptx_image_blobs(file_path)
    except Exception as e:
        logger.warning(f"pptx image extract failed (fail-open): {e}")
        return []

    if not blobs:
        return []

    out: List[ParsedChunk] = []
    for i, blob in enumerate(blobs, start=1):
        try:
            text = (await ocr_image_bytes(blob) or "").strip()
        except Exception as e:
            logger.warning(f"pptx OCR image {i} failed (fail-open): {e}")
            continue
        if len(text) < 10:
            continue
        out.append(
            ParsedChunk(
                text=f"[OCR] {text}",
                page_number=i,
                meta={"parser": "pptx", "source": "pptx_ocr", "slide_image": i},
            )
        )
    return out
