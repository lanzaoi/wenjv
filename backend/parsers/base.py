"""Pluggable document parsers → list of ParsedChunk."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Protocol, runtime_checkable
import os


@dataclass
class ParsedChunk:
    text: str
    page_number: int = 1
    meta: Dict = field(default_factory=dict)


@runtime_checkable
class DocumentParser(Protocol):
    def can_parse(self, file_path: str) -> bool: ...
    def parse(self, file_path: str) -> List[ParsedChunk]: ...


def extension_of(file_path: str) -> str:
    return os.path.splitext(file_path)[1].lower().lstrip(".")
