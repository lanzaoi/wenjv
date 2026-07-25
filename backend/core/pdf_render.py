import io
import pypdfium2 as pdfium
from backend.core.logging import get_logger

logger = get_logger()

def render_pdf_pages(file_path: str, max_pages: int = 30) -> list[bytes]:
    """
    Render PDF pages as PNG bytes. Returns list of PNG byte strings.
    """
    try:
        pdf = pdfium.PdfDocument(file_path)
    except Exception as e:
        logger.error(f"Failed to load PDF {file_path}: {e}")
        return []
        
    png_bytes_list = []
    num_pages = min(len(pdf), max_pages)
    
    for i in range(num_pages):
        try:
            page = pdf[i]
            # scale=2 gives ~144 DPI, suitable for OCR without blowing up size too much
            bitmap = page.render(scale=2)
            pil_image = bitmap.to_pil()
            
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='PNG')
            png_bytes_list.append(img_byte_arr.getvalue())
        except Exception as e:
            logger.error(f"Failed to render page {i} of {file_path}: {e}")
            
    pdf.close()
    return png_bytes_list
