"""Multimodal RAG: OCR-first caption + table extraction, Gemini VL fallback."""
from __future__ import annotations

import base64, io, logging, re
from typing import List, Optional

logger = logging.getLogger(__name__)


def extract_images_from_pdf(pdf_path: str) -> List[bytes]:
    """Render each PDF page → PNG bytes via pypdfium2."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.error("pypdfium2 not installed")
        return []

    images = []
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        for page_idx in range(len(pdf)):
            page = pdf[page_idx]
            bitmap = page.render(scale=2)
            png = bitmap.to_pil().convert("RGB")
            buf = io.BytesIO()
            png.save(buf, format="PNG")
            images.append(buf.getvalue())
        pdf.close()
    except Exception as e:
        logger.warning(f"Image extraction failed for {pdf_path}: {e}")
    return images


async def generate_caption(image_bytes: bytes, model: str = "gemini-2.0-flash") -> str:
    """OCR-first caption: PaddleOCR → text, Gemini VL fallback if empty."""
    from backend.config import settings

    # ── 1. Primary: AI Studio OCR ──
    ocr_text = await _ocr_for_caption(image_bytes, settings)
    if ocr_text and len(ocr_text.strip()) >= 10:
        return f"[OCR] {ocr_text.strip()}"

    # ── 2. Fallback: Gemini VL ──
    gemini_text = await _gemini_caption(image_bytes, settings, model)
    if gemini_text:
        return f"[Gemini] {gemini_text.strip()}"
    return ""


async def _ocr_for_caption(image_bytes: bytes, settings) -> str:
    """Run PaddleOCR on image, return extracted text."""
    try:
        from backend.core.ocr_client import ocr_image_bytes
        return (await ocr_image_bytes(image_bytes)).strip()
    except Exception as e:
        logger.warning(f"OCR caption failed, will try Gemini: {e}")
        return ""


async def _gemini_caption(image_bytes: bytes, settings, model: str) -> str:
    """Gemini VL fallback for image description."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        return ""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        img = {"mime_type": "image/png", "data": base64.b64encode(image_bytes).decode()}
        resp = genai.GenerativeModel(model).generate_content(
            ["请用中文简洁描述这张图片的内容，包括图中的文字、图表、人物、场景等。", img])
        return resp.text.strip() if resp.text else ""
    except Exception as e:
        logger.warning(f"Gemini caption failed: {e}")
        return ""


async def extract_tables_from_image(image_bytes: bytes, model: str = "gemini-2.0-flash") -> str:
    """OCR-first table extraction: PaddleOCR markdown → parse tables, Gemini fallback if empty."""
    from backend.config import settings

    # ── 1. Primary: OCR then parse markdown tables ──
    try:
        from backend.core.ocr_client import ocr_image_bytes
        ocr_text = (await ocr_image_bytes(image_bytes)).strip()
    except Exception:
        ocr_text = ""

    if ocr_text:
        tables = _extract_markdown_tables(ocr_text)
        if tables:
            return "\n\n".join(tables)

    # ── 2. Fallback: Gemini VL ──
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        return ""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        img = {"mime_type": "image/png", "data": base64.b64encode(image_bytes).decode()}
        resp = genai.GenerativeModel(model).generate_content([
            "提取这一页中的所有表格，输出为markdown表格格式。如果没有表格，只回复'无表格'三个字。", img])
        text = resp.text.strip() if resp.text else ""
        if text and text != "无表格":
            return text
    except Exception as e:
        logger.warning(f"Gemini table extraction failed: {e}")
    return ""


def _extract_markdown_tables(text: str) -> List[str]:
    """Parse markdown tables from OCR output. Returns list of markdown table strings."""
    tables = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        if _is_table_header_line(lines[i]):
            j = i + 1
            while j < len(lines) and _is_separator_line(lines[j]):
                j += 1
            if j < len(lines) and _is_table_header_line(lines[i]):
                end = j
                while end < len(lines) and ("|" in lines[end]):
                    end += 1
                table_block = "\n".join(lines[i:end])
                if "|" in table_block:
                    tables.append(table_block)
                i = end
                continue
        i += 1
    return tables


def _is_table_header_line(line: str) -> bool:
    return "|" in line and "---" not in line and len(line.strip()) > 1


def _is_separator_line(line: str) -> bool:
    return "---" in line and "|" in line


async def extract_tables_from_pdf(pdf_path: str) -> List[str]:
    """Extract tables from PDF: OCR per page, parse markdown, Gemini fallback."""
    from backend.config import settings
    tables = []
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_path)
        for page_idx in range(len(pdf)):
            page = pdf[page_idx]
            bitmap = page.render(scale=2)
            png = io.BytesIO()
            bitmap.to_pil().convert("RGB").save(png, format="PNG")
            md = await extract_tables_from_image(png.getvalue(), settings.GEMINI_VL_MODEL)
            if md:
                tables.append(md)
        pdf.close()
    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")
    return tables


async def process_pdf_images(pdf_path: str, resource_id: str = None):
    """Extract images + OCR-first captions from PDF. Returns list of Documents."""
    from langchain.schema import Document
    images = extract_images_from_pdf(pdf_path)
    if not images:
        return []
    docs = []
    for i, img_bytes in enumerate(images):
        caption = await generate_caption(img_bytes)
        if caption:
            docs.append(Document(page_content=caption, metadata={
                "source_type": "image_caption", "resource_id": resource_id or "",
                "source": "multimodal",
            }))
    return docs


def table_to_markdown(table: list) -> str:
    """Convert 2D list table to markdown table string."""
    if not table or not any(any(cell for cell in row) for row in table):
        return ""
    col_count = max(len(row) for row in table) if table else 0
    lines = []
    for i, row in enumerate(table):
        padded = list(row) + [""] * (col_count - len(row))
        lines.append("| " + " | ".join(str(c) for c in padded) + " |")
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in range(col_count)) + " |")
    return "\n".join(lines)


async def process_pdf_tables(pdf_path: str, resource_id: str = None):
    """Extract tables from PDF as Documents."""
    from langchain.schema import Document
    try:
        tables = await extract_tables_from_pdf(pdf_path)
        return [Document(page_content=md, metadata={
            "source_type": "table", "resource_id": resource_id or "",
            "source": "multimodal",
        }) for md in tables]
    except Exception:
        return []


async def process_pdf_multimodal(pdf_path: str, doc_id: str, username: str, user_id: int):
    """Process a PDF: images → OCR caption/tables → write to LanceDB."""
    from backend.config import settings
    if not settings.MULTIMODAL_ENABLED:
        logger.info("Multimodal disabled")
        return 0

    images = extract_images_from_pdf(pdf_path)
    if not images:
        return 0

    from langchain.schema import Document
    new_docs = []
    for i, img_bytes in enumerate(images):
        caption = await generate_caption(img_bytes, settings.GEMINI_VL_MODEL)
        if caption:
            new_docs.append(Document(page_content=f"[图片 {i+1}]: {caption}", metadata={
                "source_type": "image_caption", "resource_id": doc_id,
                "belongs_to": username, "user_id": str(user_id),
                "source": "multimodal", "title": f"Image {i+1} from {doc_id}",
            }))
        table_md = await extract_tables_from_image(img_bytes, settings.GEMINI_VL_MODEL)
        if table_md:
            new_docs.append(Document(page_content=f"[表格 {i+1}]:\n{table_md}", metadata={
                "source_type": "table", "resource_id": doc_id,
                "belongs_to": username, "user_id": str(user_id),
                "source": "multimodal", "title": f"Table {i+1} from {doc_id}",
            }))

    if new_docs:
        from backend.vector_store.lance_db import add_documents
        add_documents(new_docs)
        logger.info(f"Multimodal: added {len(new_docs)} entries for {doc_id}")

    return len(new_docs)
