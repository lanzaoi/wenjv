"""Shared guards for T0 image-query endpoints (search/chat by-image)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from backend.config import settings
from backend.core.image_ingest_gate import image_ingest_allowed

IMAGE_QUERY_EXTS = {".png", ".jpg", ".jpeg"}


def validate_image_query_upload(filename: Optional[str]) -> Tuple[bool, str]:
    """
    F1 + E3-style gate for query-side image upload.
    Returns (ok, detail_if_not).
    """
    name = (filename or "").strip()
    if not name:
        return False, "Filename required for image query"
    ext = Path(name).suffix.lower()
    if ext not in IMAGE_QUERY_EXTS:
        return (
            False,
            f"Unsupported image type '{ext or '(none)'}'. Allowed: png, jpg, jpeg",
        )
    allowed, reason = image_ingest_allowed(settings)
    if not allowed:
        return (
            False,
            f"Image query disabled or no extraction backend available: {reason}",
        )
    return True, "OK"
