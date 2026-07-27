from backend.config import settings
from backend.vector_store.models import StoreEngine
import sys

if settings.DEFAULT_VECTOR_DB == StoreEngine.LANCE:
    import backend.vector_store.lance_db as vector_store
elif settings.DEFAULT_VECTOR_DB == StoreEngine.CHROMA:
    import backend.vector_store.chroma_db as vector_store
elif settings.DEFAULT_VECTOR_DB == StoreEngine.MILVUS_LITE:
    import backend.vector_store.milvus_db as vector_store


def _wrap_embeddings(vs):
    if vs is not None and hasattr(vs, "embeddings"):
        from backend.core.embedding_cache import CachedEmbedder
        if not isinstance(vs.embeddings, CachedEmbedder):
            vs.embeddings = CachedEmbedder(vs.embeddings)
    return vs


def _wrap_s2l_ingestion(vs):
    if vs is None:
        return vs
    orig_add_uploaded = getattr(vs, "add_uploaded_document_content_to_vector_store", None)
    if orig_add_uploaded and not getattr(orig_add_uploaded, "_is_s2l_wrapped", False):
        def wrapped_add_uploaded(file_path, file_name, file_url, file_id, username, user_id=None):
            if not getattr(settings, "SMALL_TO_LARGE_ENABLED", False):
                return orig_add_uploaded(file_path, file_name, file_url, file_id, username, user_id=user_id)
            from backend.core.utils import load_and_chunk_document
            from backend.vector_store.models import SourceType
            from langchain_core.documents import Document
            
            texts = load_and_chunk_document(file_path, resource_id=str(file_id))
            if file_name.endswith('.md') or file_name.endswith('.markdown'):
                source_type = SourceType.NOTE
            else:
                source_type = SourceType.FILE
                
            documents = []
            for content_dict in texts:
                meta = {
                    "source": file_url,
                    "page": f"{content_dict['page_number']}",
                    "filename": file_name,
                    "belongs_to": username,
                    "user_id": str(user_id) if user_id is not None else None,
                    "file_id": f"{file_id}",
                    "resource_id": str(file_id) if file_id is not None else None,
                    "source_type": source_type
                }
                for k in ("id", "chunk_id", "chunk_group", "chunk_order"):
                    if k in content_dict:
                        meta[k] = content_dict[k]
                documents.append(Document(page_content=content_dict['text'], metadata=meta))
            vs.add_documents(documents)
            from loguru import logger
            logger.info(f"processed: {file_name} with id={file_id}")
            
        wrapped_add_uploaded._is_s2l_wrapped = True
        vs.add_uploaded_document_content_to_vector_store = wrapped_add_uploaded

    orig_add_link = getattr(vs, "add_link_content_to_vector_store", None)
    if orig_add_link and not getattr(orig_add_link, "_is_s2l_wrapped", False):
        def wrapped_add_link(link_id, url, title, text_content, username, user_id=None):
            if not getattr(settings, "SMALL_TO_LARGE_ENABLED", False):
                return orig_add_link(link_id, url, title, text_content, username, user_id=user_id)
            from backend.core.utils import chunk_link_content
            from backend.vector_store.models import SourceType
            from langchain_core.documents import Document
            
            texts = chunk_link_content(text_content, resource_id=str(link_id))
            documents = []
            for i, text in enumerate(texts):
                meta = {
                    "source": url,
                    "page": f"{i+1}",
                    "title": title,
                    "belongs_to": username,
                    "user_id": str(user_id) if user_id is not None else None,
                    "link_id": f"{link_id}",
                    "resource_id": str(link_id) if link_id is not None else None,
                    "source_type": SourceType.LINK
                }
                if hasattr(text, "metadata"):
                    for k in ("id", "chunk_id", "chunk_group", "chunk_order"):
                        if k in text.metadata:
                            meta[k] = text.metadata[k]
                documents.append(Document(page_content=f"{title}\n\n{text}", metadata=meta))
            vs.add_documents(documents)
            from loguru import logger
            logger.info(f"processed: {url} with {title}")
            
        wrapped_add_link._is_s2l_wrapped = True
        vs.add_link_content_to_vector_store = wrapped_add_link
    return vs


_wrap_embeddings(vector_store)
_wrap_s2l_ingestion(vector_store)


def vector_db():
    for name in ("backend.vector_store.lance_db", "backend.vector_store.chroma_db", "backend.vector_store.milvus_db"):
        mod = sys.modules.get(name)
        if mod is not None:
            _wrap_embeddings(mod)
            _wrap_s2l_ingestion(mod)
    return _wrap_s2l_ingestion(_wrap_embeddings(vector_store))
