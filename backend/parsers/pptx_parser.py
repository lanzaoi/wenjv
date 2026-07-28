"""PPTX helpers: text parse + optional image OCR enrichment (fail-open)."""
from __future__ import annotations

from typing import List, Tuple

from backend.parsers.base import ParsedChunk, extension_of


class PptxParser:
    def can_parse(self, file_path: str) -> bool:
        return extension_of(file_path) in {"pptx"}

    def parse(self, file_path: str) -> List[ParsedChunk]:
        try:
            from pptx import Presentation
        except ImportError as e:
            raise ValueError(
                "python-pptx is not installed; cannot parse .pptx"
            ) from e

        prs = Presentation(file_path)
        chunks: List[ParsedChunk] = []
        for idx, slide in enumerate(prs.slides, start=1):
            parts = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    t = (shape.text or "").strip()
                    if t:
                        parts.append(t)
            text = "\n".join(parts).strip()
            if text:
                chunks.append(
                    ParsedChunk(
                        text=text,
                        page_number=idx,
                        meta={"parser": "pptx", "slide": idx},
                    )
                )
        if not chunks:
            raise ValueError("PPTX has no extractable text")
        return chunks


def extract_pptx_image_blobs(file_path: str, max_images: int = 20) -> List[bytes]:
    """Best-effort extract embedded picture bytes from a PPTX (sync)."""
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        return []

    blobs: List[bytes] = []
    try:
        prs = Presentation(file_path)
        for slide in prs.slides:
            for shape in slide.shapes:
                try:
                    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                        blob = shape.image.blob
                        if blob:
                            blobs.append(blob)
                            if len(blobs) >= max_images:
                                return blobs
                except Exception:
                    continue
    except Exception:
        return blobs
    return blobs
