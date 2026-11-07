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


import os
from collections import OrderedDict

# module-level singleton
registry = ParserRegistry()

_PARSE_CACHE: OrderedDict[tuple, List[ParsedChunk]] = OrderedDict()
_MAX_PARSE_CACHE = 64


def parse_document(file_path: str) -> List[ParsedChunk]:
    if os.path.exists(file_path):
        try:
            stat = os.stat(file_path)
            cache_key = (file_path, stat.st_mtime_ns, stat.st_size)
            if cache_key in _PARSE_CACHE:
                _PARSE_CACHE.move_to_end(cache_key)
                return _PARSE_CACHE[cache_key]
        except Exception:
            cache_key = None
    else:
        cache_key = None

    res = registry.parse(file_path)
    if cache_key is not None:
        _PARSE_CACHE[cache_key] = res
        if len(_PARSE_CACHE) > _MAX_PARSE_CACHE:
            _PARSE_CACHE.popitem(last=False)
    return res
