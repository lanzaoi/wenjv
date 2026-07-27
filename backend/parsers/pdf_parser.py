from __future__ import annotations

from typing import List

from backend.core.logging import get_logger
from backend.parsers.base import ParsedChunk, extension_of

logger = get_logger()


class PdfParser:
    """Text-layer PDF via pypdf if available, else PyPDF2."""

    def can_parse(self, file_path: str) -> bool:
        if extension_of(file_path) == "pdf":
            return True
        try:
            import mimetypes
            mime, _ = mimetypes.guess_type(file_path)
            return mime == "application/pdf"
        except Exception:
            return False

    def parse(self, file_path: str) -> List[ParsedChunk]:
        reader = self._open(file_path)
        chunks: List[ParsedChunk] = []
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
            except Exception as e:
                logger.warning(f"PDF page {i+1} extract failed: {e}")
                page_text = ""
            chunks.append(
                ParsedChunk(
                    text=page_text,
                    page_number=i + 1,
                    meta={"parser": "pdf"},
                )
            )
        if not chunks:
            raise ValueError("PDF has no pages")
        joined = "".join(c.text for c in chunks).strip()
        if not joined:
            raise ValueError(
                "PDF text extraction returned empty content "
                "(scanned/image-only PDFs are not supported yet)"
            )
        return chunks

    def _open(self, file_path: str):
        from pypdf import PdfReader
        return PdfReader(file_path)
