from __future__ import annotations

from typing import List, Sequence

from backend.parsers.base import DocumentParser, ParsedChunk
from backend.parsers.text_parser import TextParser
from backend.parsers.pdf_parser import PdfParser
from backend.parsers.docx_parser import DocxParser
from backend.parsers.pptx_parser import PptxParser


def default_parsers() -> List[DocumentParser]:
    return [
        PdfParser(),
        DocxParser(),
        PptxParser(),
        TextParser(),
    ]


class ParserRegistry:
    def __init__(self, parsers: Sequence[DocumentParser] | None = None):
        self._parsers = list(parsers or default_parsers())

    def parse(self, file_path: str) -> List[ParsedChunk]:
        for parser in self._parsers:
            if parser.can_parse(file_path):
                return parser.parse(file_path)
        raise ValueError(f"No parser available for file: {file_path}")


# module-level singleton
registry = ParserRegistry()


def parse_document(file_path: str) -> List[ParsedChunk]:
    return registry.parse(file_path)
