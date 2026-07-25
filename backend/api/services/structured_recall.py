from sqlalchemy.orm import Session
from sqlalchemy import or_
from backend.database import sync_engine
from backend.api.models import Note, FileUpload, Link

def search_resources(prompt: str, user_id: int, limit: int = 20) -> list[dict]:
    """
    SQL LIKE 搜 notes.title, file_uploads.original_filename, links.title/url.
    返回: [{"resource_id": int, "source_type": str, "title": str, "source_url": str}, ...]
    """
    if not prompt or not str(prompt).strip() or user_id is None:
        return []
        
    results = []
    search_term = f"%{prompt}%"
    
    try:
        with Session(sync_engine) as session:
            # Search Notes
            notes = session.query(Note).filter(
                Note.user_id == user_id,
                Note.title.ilike(search_term)
            ).limit(limit).all()
            for note in notes:
                results.append({
                    "resource_id": note.id,
                    "source_type": "note",
                    "title": note.title,
                    "source_url": note.url or note.file_path or ""
                })
                
            # Search Files
            files = session.query(FileUpload).filter(
                FileUpload.user_id == user_id,
                FileUpload.original_filename.ilike(search_term)
            ).limit(limit).all()
            for f in files:
                results.append({
                    "resource_id": f.id,
                    "source_type": "file",
                    "title": f.original_filename,
                    "source_url": f.file_url or f.file_path or ""
                })
                
            # Search Links
            links = session.query(Link).filter(
                Link.user_id == user_id,
                or_(
                    Link.title.ilike(search_term),
                    Link.url.ilike(search_term)
                )
            ).limit(limit).all()
            for link in links:
                results.append({
                    "resource_id": link.id,
                    "source_type": "link",
                    "title": link.title,
                    "source_url": link.url or ""
                })
    except Exception as e:
        import logging
        from backend.config import settings
        logging.getLogger(settings.LOGGER_NAME).error(f"Structured recall SQL error: {e}")
        
    # Optional: we can sort by some criteria or just return the list
    return results[:limit]
