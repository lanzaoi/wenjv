import pytest
import os
from unittest.mock import patch, MagicMock, AsyncMock
from backend.worker.durable_jobs import _execute_document
from backend.api.models import IngestionJob, JobStatus, ProcessingStatus
from backend.core.image_ingest import ImageExtractionError

@pytest.fixture
def mock_session():
    session = AsyncMock()
    # Mock _mark_resource_status / _mark_resource_failed by just doing nothing or tracking
    return session

@pytest.fixture
def image_job():
    job = IngestionJob(
        id=1,
        job_type="file",
        resource_id=101,
        user_id=1,
        user_email="test@test.com",
        status=JobStatus.RUNNING,
        attempts=1,
        max_attempts=3
    )
    return job

@pytest.fixture
def image_payload(tmp_path):
    img_file = tmp_path / "test.png"
    img_file.write_bytes(b"fake_image_data")
    return {
        "file_path": str(img_file),
        "file_name": "test.png",
        "file_url": "/file/test.png",
    }

@pytest.mark.asyncio
async def test_image_job_success(mock_session, image_job, image_payload):
    with patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract, \
         patch("backend.worker.durable_jobs.vector_store") as mock_vector_store, \
         patch("backend.worker.durable_jobs._mark_resource_status", new_callable=AsyncMock) as mock_mark_status, \
         patch("backend.worker.durable_jobs.settings") as mock_settings:
         
        mock_settings.IMAGE_INGEST_ENABLED = True
        mock_extract.return_value = "[OCR] Hello Image"
        mock_vector_store.add_uploaded_document_content_to_vector_store = MagicMock()
        
        await _execute_document(mock_session, image_job, image_payload)
        
        mock_extract.assert_called_once_with(b"fake_image_data", filename="test.png")
        # Ensure it went to the vector store
        mock_vector_store.add_uploaded_document_content_to_vector_store.assert_called_once()
        
        # Ensure finished status
        mock_mark_status.assert_called_with(mock_session, image_job, ProcessingStatus.FINISHED, None)
        
        # Verify the temp file was created with correct content
        temp_file = image_payload["file_path"] + ".img.md"
        assert os.path.exists(temp_file)
        with open(temp_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "# Image: test.png" in content
        assert "[OCR] Hello Image" in content

@pytest.mark.asyncio
async def test_image_job_failed_extraction(mock_session, image_job, image_payload):
    with patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract, \
         patch("backend.worker.durable_jobs.vector_store") as mock_vector_store, \
         patch("backend.worker.durable_jobs._mark_resource_failed", new_callable=AsyncMock) as mock_mark_failed, \
         patch("backend.worker.durable_jobs._mark_resource_status", new_callable=AsyncMock) as mock_mark_status, \
         patch("backend.worker.durable_jobs.settings") as mock_settings:
         
        mock_settings.IMAGE_INGEST_ENABLED = True
        mock_extract.side_effect = ImageExtractionError("neither OCR nor Gemini yielded text")
        mock_vector_store.add_uploaded_document_content_to_vector_store = MagicMock()
        
        await _execute_document(mock_session, image_job, image_payload)
        
        mock_extract.assert_called_once()
        # Ensure it did NOT go to vector store
        mock_vector_store.add_uploaded_document_content_to_vector_store.assert_not_called()
        
        # Ensure failed status
        mock_mark_failed.assert_called_once()
        args, _ = mock_mark_failed.call_args
        assert "Image extraction failed" in args[2]

@pytest.mark.asyncio
async def test_image_job_disabled(mock_session, image_job, image_payload):
    with patch("backend.core.image_ingest.extract_text_from_image_bytes", new_callable=AsyncMock) as mock_extract, \
         patch("backend.worker.durable_jobs._mark_resource_failed", new_callable=AsyncMock) as mock_mark_failed, \
         patch("backend.worker.durable_jobs._mark_resource_status", new_callable=AsyncMock) as mock_mark_status, \
         patch("backend.worker.durable_jobs.settings") as mock_settings:
         
        mock_settings.IMAGE_INGEST_ENABLED = False
        
        await _execute_document(mock_session, image_job, image_payload)
        
        mock_extract.assert_not_called()
        mock_mark_failed.assert_called_once()
        args, _ = mock_mark_failed.call_args
        assert "requires IMAGE_INGEST_ENABLED=true" in args[2]
