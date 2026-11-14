import io
import logging
import os
import re
import threading
import time
from typing import Any, Literal

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import pypdfium2 as pdfium
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
logger = logging.getLogger("wenjv-ocr-sidecar")

OcrMode = Literal["auto", "general", "formula"]

_MATH_SIGNAL_RE = re.compile(
    r"([=≈≠≤≥±∑∫√∞∆Δδφλμπθασωγ∂∇×÷^_]|\\[a-zA-Z]+)"
)

app = FastAPI(title="Wenjv Local CPU OCR Sidecar", version="0.1.0")

_rapid_lock = threading.Lock()
_p2t_lock = threading.Lock()
_rapid_engine: Any = None
_p2t_engine: Any = None


def _get_rapidocr() -> Any:
    global _rapid_engine
    if _rapid_engine is not None:
        return _rapid_engine
    with _rapid_lock:
        if _rapid_engine is not None:
            return _rapid_engine
        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

        logger.info("Initializing RapidOCR (PP-OCRv5 Mobile ONNX CPU)...")
        _rapid_engine = RapidOCR(
            params={
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
            }
        )
        return _rapid_engine


def _get_pix2text() -> Any:
    global _p2t_engine
    if _p2t_engine is not None:
        return _p2t_engine
    with _p2t_lock:
        if _p2t_engine is not None:
            return _p2t_engine
        from pix2text import Pix2Text

        logger.info("Initializing Pix2Text (MFD + MFR ONNX CPU)...")
        _p2t_engine = Pix2Text.from_config(device="cpu")
        return _p2t_engine


def _looks_like_math(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 12:
        # Very sparse general OCR might indicate dense isolated formulas/diagrams
        return True
    hits = _MATH_SIGNAL_RE.findall(stripped)
    return len(hits) >= 2


def _run_rapidocr(pil_img: Image.Image) -> str:
    engine = _get_rapidocr()
    rgb_img = pil_img.convert("RGB")
    arr = np.array(rgb_img)
    res = engine(arr)
    txts = getattr(res, "txts", None) or []
    lines = [str(line).strip() for line in txts if str(line).strip()]
    return "\n".join(lines)


def _run_pix2text(pil_img: Image.Image) -> str:
    engine = _get_pix2text()
    rgb_img = pil_img.convert("RGB")
    out = engine.recognize_text_formula(rgb_img, return_text=True)
    return str(out or "").strip()


def _recognize_pil(pil_img: Image.Image, mode: OcrMode) -> tuple[str, str]:
    # Always normalize EXIF orientation first
    normalized = ImageOps.exif_transpose(pil_img).convert("RGB")

    # Downscale giant images (> 2400px long edge) for predictable CPU latency
    max_dim = 2400
    w, h = normalized.size
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        normalized = normalized.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    rapid_text = _run_rapidocr(normalized)

    if mode == "general":
        return rapid_text, "ppocrv5-mobile"

    use_formula = mode == "formula" or _looks_like_math(rapid_text)
    if not use_formula:
        return rapid_text, "ppocrv5-mobile"

    p2t_text = ""
    try:
        p2t_text = _run_pix2text(normalized)
    except Exception as exc:
        logger.warning("Pix2Text failed, falling back to PP-OCRv5 Mobile: %s", exc)

    if rapid_text and p2t_text:
        combined = (
            f"[文本与行内识别 (PP-OCRv5 Mobile)]\n{rapid_text}\n\n"
            f"[公式与版面识别 (Pix2Text)]\n{p2t_text}"
        )
        return combined, "ppocrv5-mobile+pix2text"
    if p2t_text:
        return p2t_text, "pix2text"
    return rapid_text, "ppocrv5-mobile"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "engines": {
            "ppocrv5_mobile_loaded": _rapid_engine is not None,
            "pix2text_loaded": _p2t_engine is not None,
        },
    }


@app.post("/ocr/image")
async def ocr_image(
    file: UploadFile = File(...),
    mode: str = Form("auto"),
) -> dict[str, Any]:
    norm_mode: OcrMode = mode if mode in ("auto", "general", "formula") else "auto"
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image upload")

    t0 = time.perf_counter()
    try:
        with Image.open(io.BytesIO(raw)) as img:
            text, engine_name = _recognize_pil(img, norm_mode)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image or OCR error: {exc}") from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "text": text,
        "engine": engine_name,
        "mode": norm_mode,
        "elapsed_ms": elapsed_ms,
    }


@app.post("/ocr/pdf")
async def ocr_pdf(
    file: UploadFile = File(...),
    mode: str = Form("general"),
    max_pages: int = Form(12),
) -> dict[str, Any]:
    norm_mode: OcrMode = mode if mode in ("auto", "general", "formula") else "general"
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    t0 = time.perf_counter()
    page_outputs: list[str] = []
    engines_used: set[str] = set()
    capped_pages = max(1, min(int(max_pages), 50))

    try:
        doc = pdfium.PdfDocument(raw)
        num_pages = min(len(doc), capped_pages)
        for i in range(num_pages):
            page = doc[i]
            bitmap = page.render(scale=150.0 / 72.0)
            pil_img = bitmap.to_pil()
            page_text, eng = _recognize_pil(pil_img, norm_mode)
            engines_used.add(eng)
            if page_text.strip():
                page_outputs.append(f"## 第 {i + 1} 页\n{page_text.strip()}")
            page.close()
        doc.close()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF OCR failed: {exc}") from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "text": "\n\n".join(page_outputs),
        "engine": "+".join(sorted(engines_used)) if engines_used else "ppocrv5-mobile",
        "mode": norm_mode,
        "elapsed_ms": elapsed_ms,
        "pages": len(page_outputs),
    }


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("OCR_HOST", "127.0.0.1")
    port = int(os.environ.get("OCR_PORT", "8788"))
    uvicorn.run(app, host=host, port=port, log_level="info")
