# backend/core/structure_chunker.py
"""
Structure-aware chunker with atomic block protection (tables & code blocks)
and hierarchical header breadcrumb path injection.
"""
from __future__ import annotations

import re
from typing import List, Dict, Any
from backend.config import settings


def parse_markdown_blocks(text: str) -> List[Dict[str, Any]]:
    """
    Parse text into structured markdown blocks:
    - heading: {type: 'heading', level: int, title: str}
    - code: {type: 'code', lang: str, content: str}
    - table: {type: 'table', lines: list[str], content: str}
    - text: {type: 'text', content: str}
    """
    lines = text.split("\n")
    blocks: List[Dict[str, Any]] = []
    i = 0
    n = len(lines)

    in_code = False
    code_lines: List[str] = []
    code_lang = ""

    table_lines: List[str] = []

    def flush_table():
        nonlocal table_lines
        if table_lines:
            blocks.append({
                "type": "table",
                "lines": list(table_lines),
                "content": "\n".join(table_lines),
            })
            table_lines = []

    header_re = re.compile(r"^(#{1,6})\s+(.+)$")
    table_row_re = re.compile(r"^\s*\|.*\|\s*$")
    code_start_re = re.compile(r"^\s*```(\w*)\s*$")
    code_end_re = re.compile(r"^\s*```\s*$")

    text_buf: List[str] = []

    def flush_text():
        nonlocal text_buf
        if text_buf:
            content = "\n".join(text_buf).strip()
            if content:
                blocks.append({"type": "text", "content": content})
            text_buf = []

    while i < n:
        line = lines[i]

        # Check code block fence
        if not in_code and code_start_re.match(line):
            flush_text()
            flush_table()
            in_code = True
            m = code_start_re.match(line)
            code_lang = m.group(1) if m else ""
            code_lines = [line]
            i += 1
            continue
        elif in_code:
            code_lines.append(line)
            if code_end_re.match(line):
                in_code = False
                blocks.append({
                    "type": "code",
                    "lang": code_lang,
                    "content": "\n".join(code_lines),
                })
                code_lines = []
            i += 1
            continue

        # Check table row
        if table_row_re.match(line):
            flush_text()
            table_lines.append(line)
            i += 1
            continue
        else:
            flush_table()

        # Check heading
        hm = header_re.match(line.strip())
        if hm:
            flush_text()
            blocks.append({
                "type": "heading",
                "level": len(hm.group(1)),
                "title": hm.group(2).strip(),
            })
            i += 1
            continue

        text_buf.append(line)
        i += 1

    flush_text()
    flush_table()
    if in_code and code_lines:
        blocks.append({
            "type": "code",
            "lang": code_lang,
            "content": "\n".join(code_lines),
        })

    return blocks


def chunk_table_block(table_lines: List[str], max_atomic_size: int = 1200) -> List[str]:
    """
    Split table into sub-tables with repeated headers if size exceeds max_atomic_size.
    Preserves table syntax and column definitions for all slices.
    """
    full_table = "\n".join(table_lines)
    if len(full_table) <= max_atomic_size or len(table_lines) <= 3:
        return [full_table]

    headers = table_lines[:2]  # col header + divider
    rows = table_lines[2:]

    sub_tables = []
    curr_batch: List[str] = []
    curr_len = sum(len(h) + 1 for h in headers)

    for r in rows:
        r_len = len(r) + 1
        if curr_batch and (curr_len + r_len > max_atomic_size):
            sub_tables.append("\n".join(headers + curr_batch))
            curr_batch = [r]
            curr_len = sum(len(h) + 1 for h in headers) + r_len
        else:
            curr_batch.append(r)
            curr_len += r_len

    if curr_batch:
        sub_tables.append("\n".join(headers + curr_batch))

    return sub_tables if sub_tables else [full_table]


def chunk_code_block(code_content: str, lang: str = "", max_atomic_size: int = 1200) -> List[str]:
    """
    Split code block across line boundaries if size exceeds max_atomic_size.
    Wraps each slice with fenced code markers so syntax is preserved.
    """
    if len(code_content) <= max_atomic_size:
        return [code_content]

    lines = code_content.split("\n")
    # Strip opening and closing fence if present
    inner_lines = lines
    if inner_lines and inner_lines[0].strip().startswith("```"):
        inner_lines = inner_lines[1:]
    if inner_lines and inner_lines[-1].strip() == "```":
        inner_lines = inner_lines[:-1]

    sub_blocks = []
    curr_batch: List[str] = []
    curr_len = len(lang) + 8

    for line in inner_lines:
        l_len = len(line) + 1
        if curr_batch and (curr_len + l_len > max_atomic_size):
            sub_blocks.append(f"```{lang}\n" + "\n".join(curr_batch) + "\n```")
            curr_batch = [line]
            curr_len = len(lang) + 8 + l_len
        else:
            curr_batch.append(line)
            curr_len += l_len

    if curr_batch:
        sub_blocks.append(f"```{lang}\n" + "\n".join(curr_batch) + "\n```")

    return sub_blocks if sub_blocks else [code_content]


def structure_aware_chunk(
    body: str,
    splitter: Any = None,
    max_atomic_size: int = 1200,
    page_number: int = 1,
) -> List[Dict[str, Any]]:
    """
    Split document text using structure-aware parsing:
    - Maintains heading breadcrumb hierarchy stack
    - Preserves atomic blocks (tables & code) without splitting across boundaries
    - Injects [breadcrumbs] into indexing_text, keeps text pure clean for LLM assembly
    """
    blocks = parse_markdown_blocks(body)
    breadcrumbs_stack: List[tuple[int, str]] = []
    chunks: List[Dict[str, Any]] = []

    char_cursor = 0

    for b in blocks:
        b_type = b["type"]

        if b_type == "heading":
            level = b["level"]
            title = b["title"]
            while breadcrumbs_stack and breadcrumbs_stack[-1][0] >= level:
                breadcrumbs_stack.pop()
            breadcrumbs_stack.append((level, title))
            continue

        header_str = " > ".join(t for _, t in breadcrumbs_stack)
        sub_texts: List[str] = []

        if b_type == "table":
            sub_texts = chunk_table_block(b["lines"], max_atomic_size=max_atomic_size)
        elif b_type == "code":
            sub_texts = chunk_code_block(b["content"], lang=b.get("lang", ""), max_atomic_size=max_atomic_size)
        else:
            content = b["content"]
            if splitter is not None:
                sub_texts = splitter.split_text(content)
            else:
                sub_texts = [content]

        for st in sub_texts:
            if not st.strip():
                continue
            start_pos = body.find(st, char_cursor)
            if start_pos == -1:
                start_pos = char_cursor
            end_pos = start_pos + len(st)
            char_cursor = end_pos

            indexing_text = (
                f"[{header_str}]\n\n{st}"
                if (header_str and getattr(settings, "BI_TEXT_INDEXING_ENABLED", True))
                else st
            )

            chunks.append({
                "text": st,
                "indexing_text": indexing_text,
                "header_str": header_str,
                "block_type": b_type,
                "start_char": start_pos,
                "end_char": end_pos,
                "page_number": page_number,
            })

    # Fallback if no chunks produced (e.g. empty or non-markdown)
    if not chunks and body.strip():
        if splitter is not None:
            raw_splits = splitter.split_text(body)
        else:
            raw_splits = [body]
        for idx, rs in enumerate(raw_splits):
            chunks.append({
                "text": rs,
                "indexing_text": rs,
                "header_str": "",
                "block_type": "text",
                "start_char": 0,
                "end_char": len(rs),
                "page_number": page_number,
            })

    return chunks
