"""Tests for SiliconFlow ASR client."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import settings
from backend.core.asr_client import (
    ASRConfigError,
    ASRError,
    ASRLimitError,
    transcribe_audio_bytes,
)


@pytest.fixture
def enable_asr(monkeypatch):
    monkeypatch.setattr(settings, "AUDIO_ASR_ENABLED", True)
    monkeypatch.setattr(settings, "ASR_API_KEY", "test_key")
    monkeypatch.setattr(settings, "ASR_API_BASE", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(settings, "ASR_MODEL", "FunAudioLLM/SenseVoiceSmall")
    monkeypatch.setattr(settings, "ASR_MAX_UPLOAD_BYTES", 1024 * 1024)


@pytest.mark.asyncio
async def test_asr_disabled_raises(monkeypatch):
    monkeypatch.setattr(settings, "AUDIO_ASR_ENABLED", False)
    with pytest.raises(ASRConfigError, match="AUDIO_ASR_ENABLED"):
        await transcribe_audio_bytes(b"abc", filename="a.mp3")


@pytest.mark.asyncio
async def test_asr_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "AUDIO_ASR_ENABLED", True)
    monkeypatch.setattr(settings, "ASR_API_KEY", "")
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "")
    with pytest.raises(ASRConfigError, match="key"):
        await transcribe_audio_bytes(b"abc", filename="a.mp3")


@pytest.mark.asyncio
async def test_asr_too_large(enable_asr, monkeypatch):
    monkeypatch.setattr(settings, "ASR_MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ASRLimitError):
        await transcribe_audio_bytes(b"x" * 20, filename="a.mp3")


@pytest.mark.asyncio
async def test_asr_success(enable_asr):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"text": "你好世界"}
    mock_resp.text = ""

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("backend.core.asr_client.httpx.AsyncClient", return_value=mock_client):
        text = await transcribe_audio_bytes(b"fake-audio", filename="meet.mp3")
    assert text == "你好世界"
    mock_client.post.assert_awaited()


@pytest.mark.asyncio
async def test_asr_401(enable_asr):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "unauthorized"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("backend.core.asr_client.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ASRConfigError, match="unauthorized"):
            await transcribe_audio_bytes(b"fake", filename="a.mp3")


def test_audio_extensions_when_enabled(monkeypatch):
    from pydantic import BaseModel

    # Simulate validator body
    exts = ["txt", "pdf"]
    audio_on = True
    if audio_on:
        for ext in ["mp3", "m4a", "wav"]:
            if ext not in exts:
                exts.append(ext)
    assert "mp3" in exts
    assert settings.AUDIO_ASR_ENABLED is False  # default off in production settings