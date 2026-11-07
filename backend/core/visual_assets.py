"""
Visual Asset Store for Multimodal RAG (L3 & L2).
Handles image compression/standardization, on-demand PDF page rendering via pypdfium2,
disk persistence under UPLOAD_DIR/mm_assets/, and citation image resolution.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from PIL import Image

from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()


@dataclass
class VisualEvidence:
    """Represents a resolved visual asset ready for VLM consumption."""
    image_bytes: bytes
    mime_type: str
    image_path: str
    label: str
    hit_index: int
    resource_id: Optional[str] = None
    page: Optional[str] = None


def get_mm_assets_dir(resource_id: Optional[str] = None) -> Path:
    """Resolve and ensure the directory for multimodal assets."""
    base_assets = Path(settings.UPLOAD_DIR) / "mm_assets"
    if resource_id:
        target = base_assets / str(resource_id)
    else:
        target = base_assets / "common"
    target.mkdir(parents=True, exist_ok=True)
    return target


def compress_and_standardize_image(
    raw_bytes: bytes,
    max_dimension: int = 1280,
    quality: int = 85,
) -> bytes:
    """
    Standardize raw image bytes to RGB JPEG:
    - Converts RGBA/P/palette images onto a clean white background.
    - Resizes down if max(width, height) > max_dimension while preserving aspect ratio.
    - Encodes to JPEG with specified quality.
    """
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            # Handle alpha channel / palette
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                canvas = Image.new("RGB", img.size, (255, 255, 255))
                canvas.paste(img, mask=img.split()[-1])
                img = canvas
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Resize if needed
            w, h = img.size
            if max(w, h) > max_dimension:
                scale = max_dimension / float(max(w, h))
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=quality, optimize=True)
            return out_buf.getvalue()
    except Exception as e:
        logger.warning(f"Image standardization failed, returning raw bytes: {e}")
        return raw_bytes


class VisualAssetStore:
    """Deep module managing persistence and on-demand retrieval of visual assets."""

    @staticmethod
    def save_visual_asset(
        resource_id: Optional[str],
        filename: str,
        image_bytes: bytes,
        standardize: bool = True,
    ) -> str:
        """
        Compress and write an image to disk. Returns the absolute file path.
        """
        target_dir = get_mm_assets_dir(resource_id)
        stem = Path(filename).stem or "asset"
        safe_name = f"{stem}.jpg"
        target_path = target_dir / safe_name

        data = compress_and_standardize_image(image_bytes) if standardize else image_bytes
        with open(target_path, "wb") as f:
            f.write(data)

        return str(target_path)

    @staticmethod
    def render_pdf_page_snapshot(
        pdf_path: str,
        page_num: int,
        resource_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        On-demand render a 1-based page of a PDF using pypdfium2.
        Saves the snapshot to mm_assets/{resource_id}/page_{page_num}.jpg and returns path.
        """
        if not os.path.exists(pdf_path):
            return None

        target_dir = get_mm_assets_dir(resource_id or "pages")
        cached_path = target_dir / f"page_{page_num}.jpg"
        if cached_path.exists():
            return str(cached_path)

        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(pdf_path)
            idx = page_num - 1
            if idx < 0 or idx >= len(pdf):
                pdf.close()
                return None

            page = pdf[idx]
            bitmap = page.render(scale=2)  # ~144 DPI
            pil_img = bitmap.to_pil()
            pdf.close()

            buf = io.BytesIO()
            pil_img.convert("RGB").save(buf, format="JPEG", quality=85)
            compressed = compress_and_standardize_image(buf.getvalue(), max_dimension=1280)

            with open(cached_path, "wb") as f:
                f.write(compressed)

            return str(cached_path)
        except Exception as e:
            logger.warning(f"Failed to render page {page_num} of {pdf_path}: {e}")
            return None

    @classmethod
    def resolve_hit_images(
        cls,
        hits: Sequence[Tuple[Any, float, str]],
        max_images: int = 3,
    ) -> List[VisualEvidence]:
        """
        Dual-track resolution:
          Track A: Chunk has explicit image_path -> load image bytes.
          Track B: Chunk is from a PDF page without explicit crop -> render page snapshot via pypdfium2.
        Caps at max_images unique visual assets across the citations.
        """
        evidences: List[VisualEvidence] = []
        seen_keys = set()

        for i, (doc, score, source) in enumerate(hits, start=1):
            if len(evidences) >= max_images:
                break

            meta = getattr(doc, "metadata", {}) or {}
            res_id = str(meta.get("resource_id") or meta.get("file_id") or "")
            explicit_path = meta.get("image_path")
            page_str = str(meta.get("page") or "").strip()
            filename = meta.get("filename") or ""

            # Track A: Explicit image path recorded on chunk
            if explicit_path and os.path.exists(explicit_path):
                key = ("path", explicit_path)
                if key not in seen_keys:
                    seen_keys.add(key)
                    try:
                        with open(explicit_path, "rb") as f:
                            raw = f.read()
                        evidences.append(
                            VisualEvidence(
                                image_bytes=raw,
                                mime_type="image/jpeg",
                                image_path=explicit_path,
                                label=f"[引用 {i} 插图: {Path(explicit_path).name}]",
                                hit_index=i,
                                resource_id=res_id,
                                page=page_str or None,
                            )
                        )
                        continue
                    except Exception as err:
                        logger.warning(f"Failed to read image at {explicit_path}: {err}")

            # Track B: PDF page fallback
            if filename.lower().endswith(".pdf") and page_str.isdigit():
                page_int = int(page_str)
                key = ("pdf_page", filename, page_int)
                if key not in seen_keys:
                    seen_keys.add(key)
                    # Resolve pdf file location
                    candidate_paths = [
                        os.path.join(settings.UPLOAD_DIR, filename),
                        str(meta.get("source") or ""),
                    ]
                    pdf_file = next((p for p in candidate_paths if p and os.path.exists(p) and p.endswith(".pdf")), None)
                    if pdf_file:
                        snapshot_path = cls.render_pdf_page_snapshot(
                            pdf_path=pdf_file,
                            page_num=page_int,
                            resource_id=res_id or None,
                        )
                        if snapshot_path and os.path.exists(snapshot_path):
                            try:
                                with open(snapshot_path, "rb") as f:
                                    raw = f.read()
                                evidences.append(
                                    VisualEvidence(
                                        image_bytes=raw,
                                        mime_type="image/jpeg",
                                        image_path=snapshot_path,
                                        label=f"[引用 {i} 第 {page_int} 页快照]",
                                        hit_index=i,
                                        resource_id=res_id,
                                        page=str(page_int),
                                    )
                                )
                            except Exception as err:
                                logger.warning(f"Failed to read snapshot at {snapshot_path}: {err}")

        return evidences

    @classmethod
    def resolve_image_from_identifier(cls, identifier: str) -> Optional[Tuple[bytes, str]]:
        """
        Resolve an image from:
        1. data URI: data:image/jpeg;base64,...
        2. raw base64 string
        3. relative API path: /api/documents/assets/image?path=...
        4. local absolute or relative filesystem path
        Returns (image_bytes, mime_type) or None.
        """
        if not identifier or not isinstance(identifier, str):
            return None
        s = identifier.strip()

        # Case 1: data URI
        if s.startswith("data:image/") and ";base64," in s:
            try:
                header, b64_data = s.split(";base64,", 1)
                mime = header.replace("data:", "") or "image/jpeg"
                import base64
                return base64.b64decode(b64_data), mime
            except Exception as e:
                logger.warning(f"Failed to decode data URI image: {e}")
                return None

        # Case 2: URL containing query param path=...
        if "path=" in s:
            try:
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(s)
                qs = parse_qs(parsed.query)
                p = qs.get("path", [None])[0]
                if p:
                    s = p
            except Exception:
                pass

        # Case 3: local file path
        candidate_paths = [
            s,
            os.path.join(settings.UPLOAD_DIR, s.lstrip("/")),
            os.path.join(settings.UPLOAD_DIR, "mm_assets", s.lstrip("/")),
        ]
        upload_dir_path = Path(settings.UPLOAD_DIR).resolve()
        for cp in candidate_paths:
            try:
                p = Path(cp).resolve()
                # Security: ensure inside upload dir or mm_assets
                if p.is_file() and p.is_relative_to(upload_dir_path):
                    with open(p, "rb") as f:
                        data = f.read()
                    ext = p.suffix.lower()
                    mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
                    return data, mime
            except Exception:
                continue

        # Case 4: maybe pure base64 string (>100 chars, no spaces)
        if len(s) > 100 and " " not in s and "\n" not in s:
            try:
                import base64
                decoded = base64.b64decode(s)
                if len(decoded) > 10:
                    return decoded, "image/jpeg"
            except Exception:
                pass

        return None

