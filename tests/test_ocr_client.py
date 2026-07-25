import pytest
from unittest.mock import patch, MagicMock
from backend.config import settings
from backend.core.ocr_client import ocr_image_bytes, OCRError, OCRTimeoutError, OCRConfigError

@pytest.fixture(autouse=True)
def reset_settings():
    settings.OCR_MODE = "on"
    settings.OCR_AISTUDIO_ACCESS_TOKEN = "test-token"
    settings.OCR_TIMEOUT_SECONDS = 2
    yield

@pytest.mark.asyncio
async def test_ocr_missing_token():
    settings.OCR_AISTUDIO_ACCESS_TOKEN = ""
    with pytest.raises(OCRConfigError, match="OCR_AISTUDIO_ACCESS_TOKEN is not set"):
        await ocr_image_bytes(b"test")

@pytest.mark.asyncio
async def test_ocr_success():
    with patch('backend.core.ocr_client.httpx.AsyncClient.post') as m_post, \
         patch('backend.core.ocr_client.httpx.AsyncClient.get') as m_get, \
         patch('backend.core.ocr_client.asyncio.sleep') as m_sleep:
         
        # Mock submit
        m_submit_resp = MagicMock()
        m_submit_resp.json.return_value = {"data": {"jobId": "job123"}}
        m_post.return_value = m_submit_resp
        
        # Mock poll (2nd call) then download (3rd call)
        m_poll_resp = MagicMock()
        m_poll_resp.json.return_value = {
            "data": {"state": "done", "resultUrl": {"jsonUrl": "http://jsonurl"}}
        }
        
        m_download_resp = MagicMock()
        m_download_resp.text = '{"layoutParsingResults": [{"markdown": {"text": "hello OCR"}}]}\n{"layoutParsingResults": [{"markdown": {"text": "line 2"}}]}'
        
        m_get.side_effect = [m_poll_resp, m_download_resp]
        
        text = await ocr_image_bytes(b"image")
        
        assert text == "hello OCR\n\nline 2"
        m_post.assert_called_once()
        assert m_get.call_count == 2
        
@pytest.mark.asyncio
async def test_ocr_timeout():
    settings.OCR_TIMEOUT_SECONDS = 0.1
    
    with patch('backend.core.ocr_client.httpx.AsyncClient.post') as m_post, \
         patch('backend.core.ocr_client.httpx.AsyncClient.get') as m_get, \
         patch('backend.core.ocr_client.time.time') as m_time:
         
        m_submit_resp = MagicMock()
        m_submit_resp.json.return_value = {"data": {"jobId": "job123"}}
        m_post.return_value = m_submit_resp
        
        # Force timeout condition in loop
        m_time.side_effect = [0, 1]  # start_time=0, current_time=1 (1 > 0.1 timeout)
        
        with pytest.raises(OCRTimeoutError, match="timed out"):
            await ocr_image_bytes(b"image")
