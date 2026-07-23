from __future__ import annotations

from typing import List

from backend.core.logging import get_logger
from backend.parsers.base import DocumentParser, ParsedChunk, extension_of

logger = get_logger()


class TextParser:
    """UTF-8 text: txt, md, markdown, json, sh, csv, log."""

    EXTS = {"txt", "md", "markdown", "json", "sh", "csv", "log", "text"}

    def can_parse(self, file_path: str) -> bool:
        return extension_of(file_path) in self.EXTS

    def parse(self, file_path: str) -> List[ParsedChunk]:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            raise ValueError(f"Empty text file: {file_path}")
        return [ParsedChunk(text=content, page_number=1, meta={"parser": "text"})]
