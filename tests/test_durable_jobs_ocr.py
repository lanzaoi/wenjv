import pytest
import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock
from backend.config import settings
from backend.worker.durable_jobs import _execute_document, ProcessingStatus
from backend.api.models import JobStatus

@pytest.mark.asyncio
async def test_execute_document_auto_ocr_skipped():
    settings.OCR_MODE = "auto"
    settings.OCR_MIN_CHARS = 40
    
    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 1
    m_job.user_email = "test@test"
    m_job.user_id = 1
    
    payload = {
        "file_path": "test.pdf",
        "file_name": "test.pdf",
        "file_url": "http://test",
    }
    
    m_parsed_chunk = MagicMock()
    m_parsed_chunk.text = "This is a normal PDF with enough text to skip OCR." * 2  # length > 40
    
    with patch('backend.parsers.parse_document', return_value=[m_parsed_chunk]) as m_parse, \
         patch('backend.core.pdf_render.render_pdf_pages') as m_render, \
         patch('backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store') as m_add, \
         patch('backend.worker.durable_jobs._mark_resource_status') as m_mark:
         
        await _execute_document(m_session, m_job, payload)
        
        # OCR skipped
        m_render.assert_not_called()
        
        # passed original file
        m_add.assert_called_once_with(
            "test.pdf", "test.pdf", "http://test", 1, "test@test", 1
        )

@pytest.mark.asyncio
async def test_execute_document_auto_ocr_triggered():
    settings.OCR_MODE = "auto"
    settings.OCR_MIN_CHARS = 40
    
    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 1
    m_job.user_email = "test@test"
    m_job.user_id = 1
    
    payload = {
        "file_path": "test2.pdf",
        "file_name": "test2.pdf",
        "file_url": "http://test",
    }
    
    m_parsed_chunk = MagicMock()
    m_parsed_chunk.text = "short"  # length = 5 < 40
    
    with patch('backend.parsers.parse_document', return_value=[m_parsed_chunk]), \
         patch('backend.core.pdf_render.render_pdf_pages', return_value=[b"png_data"]) as m_render, \
         patch('backend.core.ocr_client.ocr_image_bytes', new_callable=AsyncMock) as m_ocr, \
         patch('backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store') as m_add, \
         patch('backend.worker.durable_jobs._mark_resource_status'):
         
        m_ocr.return_value = "Extracted OCR text"
        
        await _execute_document(m_session, m_job, payload)
        
        m_render.assert_called_once()
        m_ocr.assert_called_once_with(b"png_data")
        
        # Check if the temp file was created and passed
        args, kwargs = m_add.call_args
        assert args[0] == "test2.pdf.ocr.md"
        assert args[1] == "test2.pdf"
        
        # Cleanup
        if os.path.exists("test2.pdf.ocr.md"):
            os.remove("test2.pdf.ocr.md")


@pytest.mark.asyncio
async def test_execute_document_ocr_failed():
    settings.OCR_MODE = "always"
    
    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 1
    m_job.user_email = "test@test"
    m_job.user_id = 1
    
    payload = {
        "file_path": "test3.pdf",
        "file_name": "test3.pdf",
        "file_url": "http://test",
    }
    
    m_parsed_chunk = MagicMock()
    m_parsed_chunk.text = "" 
    
    with patch('backend.parsers.parse_document', return_value=[m_parsed_chunk]), \
         patch('backend.core.pdf_render.render_pdf_pages', side_effect=Exception("Timeout!!")) as m_render, \
         patch('backend.worker.durable_jobs._mark_resource_failed', new_callable=AsyncMock) as m_fail:
         
        await _execute_document(m_session, m_job, payload)
        
        m_render.assert_called_once()
        m_fail.assert_called_once()
        assert "OCR extraction failed: Timeout!!" in m_fail.call_args[0][2]
