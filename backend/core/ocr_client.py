import httpx
import asyncio
import json
import time
import os
from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()

class OCRError(Exception):
    """Base exception for OCR errors"""
    pass

class OCRTimeoutError(OCRError):
    """Raised when OCR job polling times out"""
    pass

class OCRConfigError(OCRError):
    """Raised when OCR is enabled but misconfigured"""
    pass

async def _submit_and_poll(file_tuple: tuple) -> str:
    if settings.OCR_MODE == "off":
        return ""
        
    token = settings.OCR_AISTUDIO_ACCESS_TOKEN
    if not token:
        raise OCRConfigError("OCR is enabled but OCR_AISTUDIO_ACCESS_TOKEN is not set")
        
    api_base = settings.OCR_API_BASE.rstrip('/')
    headers = {"Authorization": f"bearer {token}"}
    
    timeout = settings.OCR_TIMEOUT_SECONDS
    
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        # 1. Submit Job
        data = {"model": settings.OCR_MODEL}
        files = {"file": file_tuple}
        
        try:
            submit_resp = await client.post(f"{api_base}/jobs", headers=headers, data=data, files=files)
            submit_resp.raise_for_status()
            job_data = submit_resp.json()
            job_id = job_data.get("data", {}).get("jobId")
            if not job_id:
                raise OCRError(f"No data.jobId in response: {job_data}")
        except Exception as e:
            logger.error(f"OCR submit failed: {e}")
            raise OCRError(f"Submit failed: {e}")
            
        # 2. Poll
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise OCRTimeoutError(f"OCR job {job_id} timed out after {timeout}s")
                
            try:
                poll_resp = await client.get(f"{api_base}/jobs/{job_id}", headers=headers)
                poll_resp.raise_for_status()
                poll_data = poll_resp.json()
                
                status = poll_data.get("data", {}).get("state")
                if status == "done":
                    json_url = poll_data.get("data", {}).get("resultUrl", {}).get("jsonUrl")
                    if not json_url:
                        raise OCRError(f"No resultUrl.jsonUrl in completed job {job_id}")
                    break
                elif status in ("failed", "error"):
                    error_msg = poll_data.get("data", {}).get("errorMsg", str(poll_data))
                    raise OCRError(f"OCR job {job_id} failed: {error_msg}")
            except httpx.HTTPStatusError as e:
                # E.g. 502/503 from the server, we might want to fail or retry.
                # Since we want to tolerate transient errors, let's log and retry.
                logger.warning(f"Poll HTTPStatusError {e.response.status_code}, retrying...")
            except httpx.RequestError as e:
                # Network layer failures (timeout, connection reset)
                logger.warning(f"Poll RequestError {e}, retrying...")
                
            await asyncio.sleep(2)
            
        # 3. Download jsonl
        try:
            jsonl_resp = await client.get(json_url)
            jsonl_resp.raise_for_status()
            jsonl_text = jsonl_resp.text
        except Exception as e:
            raise OCRError(f"Failed to download result from {json_url}: {e}")
            
        # 4. Extract text from layoutParsingResults (markdown + fallbacks)
        combined_text = []
        for line in jsonl_text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                extracted = _extract_texts_from_ocr_item(item)
                if extracted:
                    combined_text.append(extracted)
            except json.JSONDecodeError:
                continue

        return "\n\n".join(combined_text)


def _extract_texts_from_ocr_item(item: dict) -> str:
    """Pull usable text from one OCR JSONL object (multiple response shapes)."""
    chunks: list[str] = []

    results = item.get("layoutParsingResults") or item.get("result", {}).get(
        "layoutParsingResults"
    ) or []
    if isinstance(results, dict):
        results = [results]

    for res in results:
        if not isinstance(res, dict):
            continue
        # Preferred: markdown.text
        md = res.get("markdown") or {}
        if isinstance(md, dict):
            t = (md.get("text") or "").strip()
            if t:
                chunks.append(t)
        elif isinstance(md, str) and md.strip():
            chunks.append(md.strip())

        # prunedResult / overall_ocr_res style
        for key in ("prunedResult", "pruned_result", "ocrResult", "ocr_result"):
            pr = res.get(key)
            if not pr:
                continue
            if isinstance(pr, dict):
                # rec_texts: list of strings
                rec = pr.get("rec_texts") or pr.get("recTexts") or []
                if isinstance(rec, list) and rec:
                    joined = "\n".join(str(x) for x in rec if x)
                    if joined.strip():
                        chunks.append(joined.strip())
                # nested overall_ocr_res
                ocr = pr.get("overall_ocr_res") or pr.get("overallOcrRes") or {}
                if isinstance(ocr, dict):
                    rec2 = ocr.get("rec_texts") or ocr.get("recTexts") or []
                    if isinstance(rec2, list) and rec2:
                        joined = "\n".join(str(x) for x in rec2 if x)
                        if joined.strip():
                            chunks.append(joined.strip())
            elif isinstance(pr, str) and pr.strip():
                chunks.append(pr.strip())

        # plain text field
        t2 = res.get("text") or res.get("content") or ""
        if isinstance(t2, str) and t2.strip():
            chunks.append(t2.strip())

    # Top-level markdown on item
    if not chunks:
        md = item.get("markdown") or {}
        if isinstance(md, dict) and (md.get("text") or "").strip():
            chunks.append(md["text"].strip())
        t3 = item.get("text") or ""
        if isinstance(t3, str) and t3.strip():
            chunks.append(t3.strip())

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for c in chunks:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return "\n\n".join(unique)


async def ocr_file(file_path: str) -> str:
    """
    1. POST JOB_URL with file -> jobId
    2. Poll GET JOB_URL/{jobId} until 'done' or timeout
    3. Download jsonl -> extract markdown text
    4. Return combined text
    """
    if settings.OCR_MODE == "off":
        return ""
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)
        
    filename = os.path.basename(file_path)
    
    def _read_file():
        with open(file_path, "rb") as f:
            return f.read()
            
    file_bytes = await asyncio.to_thread(_read_file)
        
    return await _submit_and_poll((filename, file_bytes, "application/octet-stream"))

async def ocr_image_bytes(png_bytes: bytes) -> str:
    """Same flow for single image bytes."""
    if settings.OCR_MODE == "off":
        return ""
    return await _submit_and_poll(("image.png", png_bytes, "image/png"))
