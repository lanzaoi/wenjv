"""PptxParser unit tests + empty-slide OCR fail-open."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.parsers.pptx_parser import PptxParser, extract_pptx_image_blobs


def _make_pptx_with_text(path: Path, text: str = "Hello PPTX slide") -> None:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # blank
    box = slide.shapes.add_textbox(0, 0, prs.slide_width, prs.slide_height)
    box.text_frame.text = text
    prs.save(str(path))


def _make_empty_pptx(path: Path) -> None:
    from pptx import Presentation

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[5])
    prs.save(str(path))


def test_pptx_parser_extracts_text(tmp_path):
    p = tmp_path / "demo.pptx"
    _make_pptx_with_text(p, "Alpha slide content")
    chunks = PptxParser().parse(str(p))
    assert chunks
    assert "Alpha slide content" in chunks[0].text
    assert chunks[0].meta.get("parser") == "pptx"
    assert chunks[0].page_number == 1


def test_pptx_parser_empty_raises(tmp_path):
    p = tmp_path / "empty.pptx"
    _make_empty_pptx(p)
    with pytest.raises(ValueError, match="no extractable text"):
        PptxParser().parse(str(p))


def test_pptx_can_parse():
    assert PptxParser().can_parse("x.PPTX")
    assert not PptxParser().can_parse("x.pdf")


@pytest.mark.asyncio
async def test_pptx_ocr_empty_fail_open(tmp_path, monkeypatch):
    """OCR enrichment is fail-open: exception must not propagate as hard failure."""
    from backend.core.pptx_ocr import enrich_pptx_chunks_with_ocr
    from backend.config import settings

    monkeypatch.setattr(settings, "PPTX_OCR_EMPTY_SLIDES", True)
    p = tmp_path / "empty.pptx"
    _make_empty_pptx(p)

    with patch(
        "backend.core.ocr_client.ocr_image_bytes",
        new_callable=AsyncMock,
        side_effect=RuntimeError("ocr down"),
    ), patch(
        "backend.core.pptx_ocr.extract_pptx_image_blobs",
        return_value=[b"x"],
    ):
        extra = await enrich_pptx_chunks_with_ocr(str(p), existing_text_chars=0)
    assert extra == []


@pytest.mark.asyncio
async def test_pptx_ocr_adds_caption_when_text_thin(tmp_path, monkeypatch):
    from backend.core.pptx_ocr import enrich_pptx_chunks_with_ocr
    from backend.config import settings

    monkeypatch.setattr(settings, "PPTX_OCR_EMPTY_SLIDES", True)
    p = tmp_path / "pic.pptx"
    _make_empty_pptx(p)

    async def fake_ocr(_b: bytes) -> str:
        return "OCR from slide image"

    with patch(
        "backend.core.pptx_ocr.extract_pptx_image_blobs", return_value=[b"fake-png"]
    ), patch(
        "backend.core.ocr_client.ocr_image_bytes",
        new_callable=AsyncMock,
        side_effect=fake_ocr,
    ):
        extra = await enrich_pptx_chunks_with_ocr(str(p), existing_text_chars=0)
    assert len(extra) == 1
    assert "OCR from slide image" in extra[0].text
    assert extra[0].meta.get("source") in ("pptx_ocr", "ocr")