from langchain_chroma import Chroma
from backend.core.embedder import get_embedder
from backend.config import settings
from backend.core.logging import get_logger
from backend.core.utils import (
    chunk_link_content,
    load_and_chunk_document,
)
from backend.api.models import SourceType

logger = get_logger()

# Initialize embeddings
embeddings = get_embedder()
persist_directory = settings.CHROMA_VECTOR_STORE_PERSISTS_DIRECTORY

# Initialize Chroma vector store
vector_store = Chroma(
    embedding_function=embeddings,
    persist_directory=persist_directory
)


def add_link_content_to_vector_store(
        text_content, source, title, link_id, username):

    texts = chunk_link_content(text_content)

    documents = [
        Document(
            page_content=f"{title}\n\n{text}",
            metadata={
                "source": source,
                "page": f"{i+1}",
                "title": title,
                "belongs_to": username,
                "link_id": f"{link_id}",
                "source_type": SourceType.LINK
            }
        ) for i, text in enumerate(texts)
    ]

    ids = vector_store.add_documents(documents=documents)
    logger.info(f"processed: {source} with {title}")
    
    # Sync to FTS5
    try:
        from backend.database import sync_engine
        from backend.core.fts5_utils import insert_fts5
        with sync_engine.connect() as conn:
            raw_conn = conn.connection.dbapi_connection
            for doc, doc_id in zip(documents, ids):
                try:
                    insert_fts5(
                        raw_conn,
                        chunk_id=doc_id,
                        title=doc.metadata.get("title", ""),
                        filename=doc.metadata.get("filename", ""),
                        page_content=doc.page_content,
                        user_id=doc.metadata.get("user_id"),
                        source_type=doc.metadata.get("source_type", ""),
                        link_id=doc.metadata.get("link_id"),
                        belongs_to=doc.metadata.get("belongs_to", "")
                    )
                except Exception as e:
                    logger.error(f"FTS dual write failed for chunk_id {doc_id}: {e}")
    except Exception as e:
        logger.error(f"FTS dual write connection failed in chroma add_link_content: {e}")


def add_uploaded_document_content_to_vector_store(
        file_path, file_name, file_url, file_id, username):

    texts = load_and_chunk_document(file_path)

    if file_name.endswith('.md') or file_name.endswith('.markdown'):
        source_type = SourceType.NOTE
    else:
        source_type = SourceType.FILE

    documents = [
        Document(
            page_content=content_dict['text'],
            metadata={
                "source": file_url,
                "page": f"{content_dict['page_number']}",
                "filename": file_name,
                "belongs_to": username,
                "file_id": f"{file_id}",
                "source_type": source_type
            }
        ) for content_dict in texts
    ]

    ids = vector_store.add_documents(documents=documents)
    logger.info(f"processed: {file_name} with id={file_id}")
    
    # Sync to FTS5
    try:
        from backend.database import sync_engine
        from backend.core.fts5_utils import insert_fts5
        with sync_engine.connect() as conn:
            raw_conn = conn.connection.dbapi_connection
            for doc, doc_id in zip(documents, ids):
                try:
                    insert_fts5(
                        raw_conn,
                        chunk_id=doc_id,
                        title=doc.metadata.get("title", ""),
                        filename=doc.metadata.get("filename", ""),
                        page_content=doc.page_content,
                        user_id=doc.metadata.get("user_id"),
                        source_type=doc.metadata.get("source_type", ""),
                        link_id=doc.metadata.get("link_id"),
                        belongs_to=doc.metadata.get("belongs_to", "")
                    )
                except Exception as e:
                    logger.error(f"FTS dual write failed for chunk_id {doc_id}: {e}")
    except Exception as e:
        logger.error(f"FTS dual write connection failed in chroma add_uploaded_document: {e}")


def fetch_documents(
        include_selected,
        exclude_selected,
        window_size,
        username,
        prompt,
        source_type=None):

    if source_type == 'link':
        window_size_modified = window_size * settings.WINDOW_SIZE_MULTIPLIER
    else:
        window_size_modified = window_size

    filter_dict = {}
    if exclude_selected and include_selected:
        filter_dict = {
            "$and": [
                # Exclude these sources
                {"source": {"$nin": exclude_selected}},
                # Include these sources
                {"source": {"$in": include_selected}},
                # Include souces belonging to current users only
                {"belongs_to": {"$in": [username]}}

            ]
        }
    elif exclude_selected:
        filter_dict = {
            "$and": [
                {"source": {"$nin": exclude_selected}},
                {"belongs_to": {"$in": [username]}}

            ]
        }
    elif include_selected:
        filter_dict = {
            "$and": [
                {"source": {"$in": include_selected}},
                {"belongs_to": {"$in": [username]}}

            ]
        }
    else:
        filter_dict = {
            "belongs_to": {"$in": [username]}
        }

    if source_type is not None:
        conditions = filter_dict.get("$and")
        if conditions and isinstance(conditions, list):
            # It means there are existing conditions
            # and we need to just append new condition
            # to existing one
            conditions.append({"source_type": {"$in": [source_type]}})
            filter_dict["$and"] = conditions.copy()
        else:
            filter_dict = {
                "$and": [
                    {"source_type": {"$in": [source_type]}},
                    {"belongs_to": {"$in": [username]}}
                ]
            }

    docs = vector_store.similarity_search_with_relevance_scores(
        prompt,
        filter=filter_dict,
        k=window_size_modified  # Retrieve more relevant chunks
    )

    # TODO: Add mmr search later
    # retriever = vector_store.as_retriever(
    #    search_type="mmr",  # Maximum Marginal Relevance
    #    search_kwargs={
    #        "k": window_size,  # Number of documents to return
    #        "fetch_k": 20,  # Fetch more documents initially for diversity
    #        "lambda_mult": 0.5,  # Balance between relevance and diversity
    #        "filter": filter_dict  # Metadata filter
    #    }
    # )
    # docs = retriever.get_relevant_documents(prompt)
    return docs


def remove_documents(filename, username):
    try:
        filter_dict = {
            "$and": [
                {"filename": {"$eq": filename}},
                {"belongs_to": {"$eq": username}}
            ]
        }

        # Access the underlying Chroma collection
        # Use the get method with the where parameter
        matching_docs = vector_store._collection.get(where=filter_dict)
        if matching_docs and len(matching_docs['ids']) > 0:
            # Delete the documents using their IDs
            vector_store.delete(ids=matching_docs['ids'])
            logger.info(
                f"Removed documents with filename={filename} belonging to user={username}")
                
            # Sync remove to FTS5
            try:
                from backend.database import sync_engine
                from backend.core.fts5_utils import delete_by_filename
                with sync_engine.connect() as conn:
                    raw_conn = conn.connection.dbapi_connection
                    delete_by_filename(raw_conn, filename, belongs_to=username)
            except Exception as e:
                logger.error(f"FTS dual remove failed in chroma remove_documents: {e}")
                
            return True
        else:
            logger.warning(
                f"No documents found with filename={filename} belonging to user={username}")
            return False

    except Exception as err:
        logger.error(
            f"Error removing documents with filename={filename}: {str(err)}")
        return False


def remove_link_documents(link_id, username):
    try:
        filter_dict = {
            "$and": [
                {"link_id": {"$eq": f"{link_id}"}},
                {"belongs_to": {"$eq": username}}
            ]
        }

        # Access the underlying Chroma collection
        # Use the get method with the where parameter
        matching_docs = vector_store._collection.get(where=filter_dict)
        if matching_docs and len(matching_docs['ids']) > 0:
            # Delete the documents using their IDs
            vector_store.delete(ids=matching_docs['ids'])
            logger.info(
                f"Removed documents with link_id={link_id} belonging to user={username}")
                
            # Sync remove to FTS5
            try:
                from backend.database import sync_engine
                from backend.core.fts5_utils import delete_by_link_id
                with sync_engine.connect() as conn:
                    raw_conn = conn.connection.dbapi_connection
                    delete_by_link_id(raw_conn, link_id, belongs_to=username)
            except Exception as e:
                logger.error(f"FTS dual remove failed in chroma remove_link_documents: {e}")
                
            return True
        else:
            logger.warning(
                f"No documents found with link_id={link_id} belonging to user={username}")
            return False

    except Exception as err:
        logger.error(
            f"Error removing documents with link_id={link_id}: {str(err)}")
        return False
