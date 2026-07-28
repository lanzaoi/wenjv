"""SiliconFlow SenseVoice audio transcription client (OpenAI-compatible)."""
from __future__ import annotations

import httpx

from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()


class ASRError(Exception):
    """Base ASR error."""


class ASRConfigError(ASRError):
    """Missing key / disabled / misconfiguration."""


class ASRLimitError(ASRError):
    """File too large or duration policy exceeded."""


def _api_key() -> str:
    return (
        getattr(settings, "ASR_API_KEY", "") 
        or getattr(settings, "EMBEDDING_API_KEY", "")
        or ""
    ).strip()


def _base_url() -> str:
    base = (
        getattr(settings, "ASR_API_BASE", "")
        or "https://api.siliconflow.cn/v1"
    ).rstrip("/")
    # tolerate user pasting full .../audio/transcriptions
    if base.endswith("/audio/transcriptions"):
        base = base[: -len("/audio/transcriptions")]
    return base


async def transcribe_audio_bytes(
    data: bytes,
    filename: str = "audio.mp3",
    content_type: str | None = None,
) -> str:
    """
    POST multipart to SiliconFlow /v1/audio/transcriptions.
    Returns plain text. Raises ASR* on hard failures.
    """
    if not getattr(settings, "AUDIO_ASR_ENABLED", False):
        raise ASRConfigError("AUDIO_ASR_ENABLED is false")

    key = _api_key()
    if not key:
        raise ASRConfigError("ASR API key missing (ASR_API_KEY or EMBEDDING_API_KEY)")

    max_bytes = int(getattr(settings, "ASR_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
    if data is None or len(data) == 0:
        raise ASRError("empty audio")
    if len(data) > max_bytes:
        raise ASRLimitError(
            f"audio file exceeds {max_bytes} bytes (SiliconFlow limit ~50MB / 1h)"
        )

    url = f"{_base_url()}/audio/transcriptions"
    model = getattr(settings, "ASR_MODEL", "FunAudioLLM/SenseVoiceSmall")
    mime = content_type or "application/octet-stream"
    headers = {"Authorization": f"Bearer {key}"}
    files = {
        "file": (filename, data, mime),
        "model": (None, model),
    }
    timeout = float(getattr(settings, "ASR_TIMEOUT_SECONDS", 120))

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, files=files)
    except httpx.RequestError as e:
        logger.error(f"ASR network error: {e}")
        raise ASRError(f"ASR network error: {e}") from e

    if resp.status_code == 401:
        raise ASRConfigError("ASR unauthorized (check API key)")
    if resp.status_code >= 400:
        msg = (resp.text or "")[:300]
        logger.error(f"ASR HTTP {resp.status_code}: {msg}")
        raise ASRError(f"ASR failed HTTP {resp.status_code}: {msg}")

    try:
        payload = resp.json()
    except Exception as e:
        raise ASRError("ASR response not JSON") from e

    text = (payload.get("text") or "").strip()
    return text
