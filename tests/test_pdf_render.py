import pytest
from unittest.mock import patch, MagicMock
from backend.core.pdf_render import render_pdf_pages

def test_render_pdf_pages_success():
    with patch('backend.core.pdf_render.pdfium.PdfDocument') as m_pdf:
        # Mock PDF with 2 pages
        m_doc = MagicMock()
        m_doc.__len__.return_value = 2
        
        m_page1 = MagicMock()
        m_bitmap1 = MagicMock()
        m_pil1 = MagicMock()
        m_bitmap1.to_pil.return_value = m_pil1
        m_page1.render.return_value = m_bitmap1
        
        m_page2 = MagicMock()
        m_bitmap2 = MagicMock()
        m_pil2 = MagicMock()
        m_bitmap2.to_pil.return_value = m_pil2
        m_page2.render.return_value = m_bitmap2
        
        m_doc.__getitem__.side_effect = [m_page1, m_page2]
        
        m_pdf.return_value = m_doc
        
        # We need PIL image save to actually write bytes to the BytesIO
        def side_effect_save1(fp, format):
            fp.write(b"png1")
        m_pil1.save.side_effect = side_effect_save1
        
        def side_effect_save2(fp, format):
            fp.write(b"png2")
        m_pil2.save.side_effect = side_effect_save2
        
        results = render_pdf_pages("dummy.pdf", max_pages=30)
        
        assert len(results) == 2
        assert results[0] == b"png1"
        assert results[1] == b"png2"
        m_doc.close.assert_called_once()

def test_render_pdf_pages_error():
    with patch('backend.core.pdf_render.pdfium.PdfDocument') as m_pdf:
        m_pdf.side_effect = Exception("corrupt pdf")
        
        results = render_pdf_pages("dummy.pdf", max_pages=30)
        assert results == []

def test_render_pdf_pages_max_pages():
    with patch('backend.core.pdf_render.pdfium.PdfDocument') as m_pdf:
        m_doc = MagicMock()
        m_doc.__len__.return_value = 100
        
        m_page = MagicMock()
        m_bitmap = MagicMock()
        m_pil = MagicMock()
        m_bitmap.to_pil.return_value = m_pil
        m_page.render.return_value = m_bitmap
        m_doc.__getitem__.return_value = m_page
        
        m_pdf.return_value = m_doc
        
        def side_effect_save(fp, format):
            fp.write(b"png")
        m_pil.save.side_effect = side_effect_save
        
        results = render_pdf_pages("dummy.pdf", max_pages=3)
        assert len(results) == 3
