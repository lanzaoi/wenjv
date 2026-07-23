from __future__ import annotations

from typing import List

from backend.parsers.base import ParsedChunk, extension_of


class DocxParser:
    def can_parse(self, file_path: str) -> bool:
        return extension_of(file_path) in {"docx"}

    def parse(self, file_path: str) -> List[ParsedChunk]:
        try:
            import docx  # python-docx
        except ImportError as e:
            raise ValueError(
                "python-docx is not installed; cannot parse .docx"
            ) from e

        document = docx.Document(file_path)
        parts = []
        for p in document.paragraphs:
            t = (p.text or "").strip()
            if t:
                parts.append(t)
        # tables
        for table in document.tables:
            for row in table.rows:
                cells = [((c.text or "").strip()) for c in row.cells]
                line = " | ".join(c for c in cells if c)
                if line:
                    parts.append(line)
        text = "\n\n".join(parts).strip()
        if not text:
            raise ValueError("DOCX has no extractable text")
        return [ParsedChunk(text=text, page_number=1, meta={"parser": "docx"})]
