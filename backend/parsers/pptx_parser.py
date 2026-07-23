from __future__ import annotations

from typing import List

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
