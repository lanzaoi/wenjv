import pytest
import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock
from backend.config import settings
from backend.worker.durable_jobs import _execute_document

@pytest.mark.asyncio
async def test_ocr_stage_empty_pdf_success(monkeypatch):
    monkeypatch.setattr(settings, "OCR_MODE", "auto")
    monkeypatch.setattr(settings, "OCR_MIN_CHARS", 40)
    
    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 1
    m_job.user_email = "test@test"
    m_job.user_id = 1
    
    payload = {
        "file_path": "empty_file.pdf",
        "file_name": "empty_file.pdf",
        "file_url": "http://test",
    }
    
    # We patch parse_document to return empty for .pdf, but let it proceed for .md
    # Wait, if we mock it, we can just patch `vector_store.add_uploaded_document_content_to_vector_store`
    # The acceptance criteria "chunk contains OCR text" means we should verify the text written to temp file.
    
    m_parsed_chunk = MagicMock()
    m_parsed_chunk.text = "" 
    
    with patch('backend.parsers.parse_document', return_value=[]) as m_parse, \
         patch('backend.core.pdf_render.render_pdf_pages', return_value=[b"png_data"]) as m_render, \
         patch('backend.core.ocr_client.ocr_image_bytes', new_callable=AsyncMock) as m_ocr, \
         patch('backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store') as m_add, \
         patch('backend.worker.durable_jobs._mark_resource_status'):
         
        m_ocr.return_value = "This is OCR extracted text."
        
        await _execute_document(m_session, m_job, payload)
        
        # Verify OCR was triggered
        m_render.assert_called_once()
        m_ocr.assert_called_once_with(b"png_data")
        
        # Verify the temp file contains the OCR text
        args, kwargs = m_add.call_args
        temp_file = args[0]
        assert temp_file == "empty_file.pdf.ocr.md"
        
        with open(temp_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        assert "This is OCR extracted text." in content
        
        # Cleanup
        if os.path.exists(temp_file):
            os.remove(temp_file)

@pytest.mark.asyncio
async def test_ocr_stage_off_mode_fails(monkeypatch):
    monkeypatch.setattr(settings, "OCR_MODE", "off")
    
    m_session = AsyncMock()
    m_job = MagicMock()
    m_job.resource_id = 1
    m_job.user_email = "test@test"
    m_job.user_id = 1
    
    payload = {
        "file_path": "empty_file.pdf",
        "file_name": "empty_file.pdf",
        "file_url": "http://test",
    }
    
    with patch('backend.parsers.parse_document', return_value=[]) as m_parse, \
         patch('backend.worker.durable_jobs.vector_store.add_uploaded_document_content_to_vector_store') as m_add, \
         patch('backend.worker.durable_jobs._mark_resource_status'), \
         patch('backend.worker.durable_jobs._mark_resource_failed', new_callable=AsyncMock) as m_fail:
         
        # Make add_uploaded_document_content_to_vector_store raise exception because chunks are empty
        m_add.side_effect = ValueError("No text chunks produced for empty_file.pdf")
        
        # In real code, durable_jobs.py `execute_job` catches exceptions?
        # Wait, `_execute_document` itself doesn't catch `vector_store` exceptions, `execute_job` does!
        # But wait, we added `try-except` around OCR, but NOT around `add_uploaded_document_content_to_vector_store`!
        # Let's just check if it propagates out, which will fail the job.
        with pytest.raises(ValueError, match="No text chunks produced"):
            await _execute_document(m_session, m_job, payload)
