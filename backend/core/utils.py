import uuid
import os
import hashlib
import re
try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except ImportError:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
from backend.config import settings
import shutil
from backend.core.logging import get_logger


logger = get_logger()


text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.TEXT_SPLITTER_CHUNK_SIZE,
    chunk_overlap=settings.TEXT_SPLITTER_CHUNK_OVERLAP,
    length_function=len,
    separators=settings.TEXT_SPLITTER_SEPARATORS
)


def get_file_extension(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower().strip()


def is_allowed_upload_filename(filename: str) -> bool:
    ext = get_file_extension(filename)
    allowed = {
        e.lower().lstrip(".") for e in settings.ALLOWED_UPLOAD_EXTENSIONS
    }
    return ext in allowed


def sanitize_upload_basename(filename: str) -> str:
    """Keep a readable original suffix without path segments."""
    base = os.path.basename(filename or "upload.bin")
    # strip characters that are awkward on Windows / URLs
    safe = "".join(c if c.isalnum() or c in "._- " else "-" for c in base)
    safe = safe.strip(" .-") or "upload.bin"
    return safe[:180]


def save_file(content, title):
    # Generate a unique ID
    doc_id = str(uuid.uuid4())

    # Create a filename

    saved = False
    # Replace spaces with hyphen and remove special characters, cap length to avoid ENAMETOOLONG
    safe_title = ''.join(c if c.isalnum() else '-' for c in title).strip('-')[:100] or "note"
    filename = f"{safe_title}-{doc_id}.md"

    file_path = os.path.join(settings.UPLOAD_DIR, filename)

    # Write content to file
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        saved = True
    except Exception as err:
        logger.error(f"Error creating note {file_path}: {err}")
        saved = False

    return doc_id, file_path, filename, saved


def record_chunk_mappings(mappings: list):
    if not mappings:
        return
    try:
        from sqlalchemy.orm import Session
        from backend.database import sync_engine, ChunkMappingTable
        with Session(sync_engine) as session:
            for m in mappings:
                row = ChunkMappingTable(
                    chunk_id=str(m["chunk_id"]),
                    chunk_group=str(m["chunk_group"]),
                    chunk_order=int(m["chunk_order"]),
                    resource_id=str(m["resource_id"]) if m.get("resource_id") else None
                )
                session.merge(row)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to record batch chunk mappings: {e}")


def get_active_splitter():
    if getattr(settings, "CHUNK_EXPAND_ENABLED", False):
        chunk_size = getattr(settings, "CHUNK_RETRIEVAL_SIZE", 256)
        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=min(getattr(settings, "TEXT_SPLITTER_CHUNK_OVERLAP", 150), max(10, chunk_size // 5)),
            length_function=len,
            separators=getattr(settings, "TEXT_SPLITTER_SEPARATORS", ["\n\n", "\n", "。", "，", " ", ""])
        )
    return text_splitter


def generate_deterministic_chunk_id(resource_id: str, chunk_order: int, text_content: str, header_path: str = "") -> str:
    """Generate a deterministic, content-anchored chunk ID that remains stable across re-indexing."""
    content_snippet = text_content[:64] if text_content else ""
    seed = f"{resource_id or '0'}:{header_path}:{chunk_order}:{content_snippet}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _process_chunks_with_mapping(raw_chunks: list, resource_id: str = None):
    is_s2l = getattr(settings, "CHUNK_EXPAND_ENABLED", False)
    if not is_s2l:
        return raw_chunks
    
    chunk_group = str(resource_id) if resource_id else str(uuid.uuid4())
    mappings = []
    out = []
    total = len(raw_chunks)

    # Generate IDs (deterministic if enabled)
    chunk_ids = []
    for idx, item in enumerate(raw_chunks):
        if getattr(settings, "CHUNK_DETERMINISTIC_ID_ENABLED", True):
            cid = generate_deterministic_chunk_id(
                resource_id=str(resource_id) if resource_id else "",
                chunk_order=idx,
                text_content=item.get("text", ""),
                header_path=item.get("header_str", "")
            )
        else:
            cid = str(uuid.uuid4())
        chunk_ids.append(cid)

    for idx, item in enumerate(raw_chunks):
        chunk_id = chunk_ids[idx]
        item_copy = dict(item)
        item_copy["id"] = chunk_id
        item_copy["chunk_id"] = chunk_id
        item_copy["chunk_group"] = chunk_group
        item_copy["chunk_order"] = idx
        item_copy["prev_chunk_id"] = chunk_ids[idx - 1] if idx > 0 else None
        item_copy["next_chunk_id"] = chunk_ids[idx + 1] if idx < total - 1 else None
        mappings.append({
            "chunk_id": chunk_id,
            "chunk_group": chunk_group,
            "chunk_order": idx,
            "resource_id": resource_id
        })
        out.append(item_copy)
    record_chunk_mappings(mappings)
    return out


class ChunkString(str):
    def __new__(cls, content, metadata=None):
        obj = super().__new__(cls, content)
        obj.metadata = dict(metadata or {})
        return obj


def chunk_link_content(text_content, resource_id: str = None):
    splitter = get_active_splitter()
    splitted = splitter.split_text(text_content)
    is_s2l = getattr(settings, "CHUNK_EXPAND_ENABLED", False)
    if not is_s2l:
        return splitted
    
    chunk_group = str(resource_id) if resource_id else str(uuid.uuid4())
    mappings = []
    out = []
    for idx, s_text in enumerate(splitted):
        chunk_id = str(uuid.uuid4())
        cs = ChunkString(s_text)
        cs.metadata = {
            "id": chunk_id,
            "chunk_id": chunk_id,
            "chunk_group": chunk_group,
            "chunk_order": idx
        }
        mappings.append({
            "chunk_id": chunk_id,
            "chunk_group": chunk_group,
            "chunk_order": idx,
            "resource_id": resource_id
        })
        out.append(cs)
    record_chunk_mappings(mappings)
    return out


def load_and_chunk_document(file_path: str, resource_id: str = None, parsed_chunks: list = None):
    """
    Parse file via parser registry (or use parsed_chunks if already parsed), then apply text splitter.
    Returns list of {text, page_number}.
    """
    if parsed_chunks is not None:
        parsed = parsed_chunks
    else:
        from backend.parsers import parse_document
        parsed = parse_document(file_path)

    splitter = get_active_splitter()
    out = []
    header_regex = re.compile(r'^(#{1,6})\s+(.+)$')

    for chunk in parsed:
        page_number = chunk.page_number
        body = chunk.text or ""
        if not body.strip():
            continue

        if getattr(settings, "STRUCTURE_AWARE_CHUNKING_ENABLED", True):
            from backend.core.structure_chunker import structure_aware_chunk
            structured = structure_aware_chunk(
                body,
                splitter=splitter,
                max_atomic_size=getattr(settings, "MAX_ATOMIC_BLOCK_SIZE", 1200),
                page_number=page_number,
            )
            out.extend(structured)
        else:
            # Extract markdown heading breadcrumbs if present
            lines = body.split("\n")
            breadcrumbs_stack = []
            line_to_breadcrumb = {}
            for l_idx, line in enumerate(lines):
                m = header_regex.match(line.strip())
                if m:
                    level = len(m.group(1))
                    title = m.group(2).strip()
                    while breadcrumbs_stack and breadcrumbs_stack[-1][0] >= level:
                        breadcrumbs_stack.pop()
                    breadcrumbs_stack.append((level, title))
                line_to_breadcrumb[l_idx] = " > ".join(t for _, t in breadcrumbs_stack)

            char_cursor = 0
            for splitted_text in splitter.split_text(body):
                start_pos = body.find(splitted_text, char_cursor)
                if start_pos == -1:
                    start_pos = char_cursor
                end_pos = start_pos + len(splitted_text)
                char_cursor = end_pos

                sub_lines = body[:start_pos].count("\n")
                header_path_str = line_to_breadcrumb.get(sub_lines, "")
                indexing_text = f"[{header_path_str}]\n\n{splitted_text}" if (header_path_str and getattr(settings, "BI_TEXT_INDEXING_ENABLED", True)) else splitted_text

                out.append({
                    "text": splitted_text,
                    "indexing_text": indexing_text,
                    "header_str": header_path_str,
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "page_number": page_number,
                })
    if not out:
        raise ValueError(f"No text chunks produced for {file_path}")
    return _process_chunks_with_mapping(out, resource_id=resource_id)


def update_file_with_backup(content, filename):
    file_path = os.path.join(settings.UPLOAD_DIR, filename)
    backup_path = f"{file_path}.bak"
    # Check if original file exists
    if not os.path.exists(file_path):
        return False

    try:
        # Create backup of the original file
        shutil.copy2(file_path, backup_path)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.remove(backup_path)
            return True
        except Exception as write_err:
            logger.error(f"Error writing to file {filename}: {write_err}")
            try:
                shutil.copy2(backup_path, file_path)
                logger.info(
                    f"Restored {filename} from backup after failed update")
                os.remove(backup_path)
                return False
            except Exception as restore_err:
                logger.error(
                    f"Error restoring from backup - need manual intervention for {filename} with {backup_path}: {restore_err}")
                return False

    except Exception as backup_err:
        logger.error(f"Error creating backup of {filename}: {backup_err}")
        return False

    return False
