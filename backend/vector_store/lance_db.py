from backend.core.embedder import get_embedder
from langchain.schema import Document
import lancedb
import uuid
from backend.config import settings
from backend.core.logging import get_logger
from backend.core.utils import (
    chunk_link_content,
    load_and_chunk_document,
)
from backend.api.models import SourceType
import pyarrow as pa


logger = get_logger()

# Initialize embeddings
embeddings = get_embedder()

# Initialize LanceDB
db = lancedb.connect(settings.LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY)

# Define table name
TABLE_NAME = settings.VECTOR_STORE_COLLECTION_NAME


def _escape_filter_value(value) -> str:
    """Escape single quotes for Lance SQL-like filter literals."""
    if value is None:
        return ""
    return str(value).replace("'", "''")


# Create table if it doesn't exist
def initialize_collection():
    if TABLE_NAME not in db.table_names():
        # Create schema and table
        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(),
                     settings.EMBEDDINGS_DIMENSION)),
            pa.field("page_content", pa.string()),
            pa.field("source", pa.string()),
            pa.field("page", pa.string()),
            pa.field("title", pa.string()),
            pa.field("filename", pa.string()),
            pa.field("belongs_to", pa.string()),
            pa.field("user_id", pa.string()),
            pa.field("link_id", pa.string()),
            pa.field("file_id", pa.string()),
            pa.field("source_type", pa.string()),
            pa.field("resource_id", pa.string()),
            pa.field("chunk_group", pa.string()),
            pa.field("chunk_order", pa.int32())
        ])

        # Create empty table with schema
        db.create_table(TABLE_NAME, schema=schema)

        table = db.open_table(TABLE_NAME)

        # Scalar indexes for metadata filters
        for col in ("belongs_to", "user_id", "source_type", "source", "filename", "link_id"):
            try:
                table.create_scalar_index(col, index_type="BTREE")
            except Exception as e:
                logger.warning(f"scalar index on {col}: {e}")
        logger.info(f"Created new LanceDB table: {TABLE_NAME}")
    else:
        logger.info(f"Using existing LanceDB table: {TABLE_NAME}")


def _schema_names(table) -> set:
    try:
        schema = table.schema
        names = getattr(schema, "names", None)
        if names is not None:
            return set(names)
        return {f.name for f in schema}
    except Exception:
        return set()


def ensure_vector_ann_index(table=None, min_rows: int = 256) -> bool:
    """
    Best-effort ANN index creation (IVF/HNSW depending on Lance version).
    Small tables stay on flat scan — index build is deferred until min_rows.

    NOTE: Never call create_index(\"vector\") — Lance treats the first positional
    arg as *metric*, so metric='vector' raises Invalid distance type.
    """
    try:
        table = table or db.open_table(TABLE_NAME)
        try:
            n = table.count_rows()
        except Exception:
            n = 0
        if n < min_rows:
            logger.debug(f"skip vector index: only {n} rows (<{min_rows})")
            return False

        # Prefer simpler indexes first — IVF_PQ panics/unwraps on zero vectors
        # or degenerate data; cosine metric is required (not positional "vector").
        dim = int(getattr(settings, "EMBEDDINGS_DIMENSION", 1024) or 1024)
        nparts = min(256, max(2, n // 40))
        # num_sub_vectors must divide dimension for PQ
        nsub = 16 if dim % 16 == 0 else (8 if dim % 8 == 0 else 4)

        errors = []
        attempts = [
            # 1) IVF_FLAT / default cosine on named column (safest)
            lambda: table.create_index(
                metric="cosine",
                vector_column_name="vector",
            ),
            # 2) Explicit IVF_PQ with safe sub-vector count
            lambda: table.create_index(
                metric="cosine",
                vector_column_name="vector",
                index_type="IVF_PQ",
                num_partitions=nparts,
                num_sub_vectors=nsub,
            ),
            # 3) Older Lance: keyword-only metric, no vector_column_name
            lambda: table.create_index(metric="cosine"),
        ]
        for fn in attempts:
            try:
                fn()
                logger.info(f"vector ANN index ensured on {TABLE_NAME} (rows={n})")
                return True
            except Exception as e:
                errors.append(str(e))
        # Flat scan is fine — do not raise
        logger.warning(
            f"vector index not created (flat scan OK): {errors[-1] if errors else 'unknown'}"
        )
        return False
    except Exception as e:
        logger.warning(f"ensure_vector_ann_index failed: {e}")
        return False


# Initialize table
initialize_collection()


def add_documents(documents):
    """Add documents to the LanceDB vector store"""
    if not documents:
        return

    # Generate embeddings for documents
    texts = [doc.page_content for doc in documents]
    embeddings_list = embeddings.embed_documents(texts)

    table = db.open_table(TABLE_NAME)
    names = _schema_names(table)

    # Prepare data for LanceDB
    data = []
    for i, (doc, embedding) in enumerate(zip(documents, embeddings_list)):
        # Generate a unique UUID for each document
        doc_id = str(uuid.uuid4())

        # Create entity with all fields
        entity = {
            "id": doc_id,
            "vector": embedding,
            "page_content": doc.page_content,
        }

        # Add all metadata fields
        for key, value in doc.metadata.items():
            entity[key] = value if value is None else str(value) if key == "user_id" else value

        # Ensure common fields exist
        for field in ["source", "page", "title", "filename", "belongs_to",
                      "link_id", "file_id", "source_type", "user_id", "resource_id",
                      "chunk_group", "chunk_order"]:
            if field not in entity:
                entity[field] = None

        # Drop unknown columns for older tables without user_id etc.
        if names:
            entity = {k: v for k, v in entity.items() if k in names}

        data.append(entity)

    table.add(data)
    logger.info(f"Added {len(documents)} documents to LanceDB table")
    # Deferred ANN index (no-op under min_rows)
    ensure_vector_ann_index(table)

    # Sync to FTS5
    try:
        from backend.database import sync_engine
        from backend.core.fts5_utils import insert_fts5
        with sync_engine.connect() as conn:
            raw_conn = conn.connection.dbapi_connection
            for entity in data:
                try:
                    insert_fts5(
                        raw_conn,
                        chunk_id=entity["id"],
                        title=entity.get("title", ""),
                        filename=entity.get("filename", ""),
                        page_content=entity.get("page_content", ""),
                        user_id=entity.get("user_id"),
                        source_type=entity.get("source_type", ""),
                        link_id=entity.get("link_id"),
                        belongs_to=entity.get("belongs_to", ""),
                        resource_id=entity.get("resource_id"),
                    )
                except Exception as e:
                    logger.error(f"FTS dual write failed for chunk_id {entity['id']}: {e}")
    except Exception as e:
        logger.error(f"FTS dual write connection failed in add_documents: {e}")

    # Sync to ChunkMappingTable for small-to-large retrieval
    try:
        from backend.database import sync_engine, ChunkMappingTable
        from sqlalchemy.orm import Session
        with Session(sync_engine) as session:
            for entity in data:
                g = entity.get("chunk_group")
                if g is None:
                    continue
                o = entity.get("chunk_order")
                if o is None:
                    continue
                existing = session.query(ChunkMappingTable).filter(
                    ChunkMappingTable.chunk_id == entity["id"]).first()
                if not existing:
                    session.add(ChunkMappingTable(
                        chunk_id=entity["id"],
                        chunk_group=str(g),
                        chunk_order=int(o),
                        resource_id=entity.get("resource_id", "")))
            session.commit()
    except Exception as e:
        logger.warning(f"ChunkMappingTable sync failed (non-fatal): {e}")

    # Sync to DocEmbeddingTable for late chunking
    if getattr(settings, "LATE_CHUNKING_ENABLED", False):
        try:
            from backend.database import sync_engine, DocEmbeddingTable
            from sqlalchemy.orm import Session
            import numpy as np, struct
            # Compute average vector per resource_id
            rid_vecs = {}
            rid_counts = {}
            for entity in data:
                rid = entity.get("resource_id", "")
                if not rid:
                    continue
                raw = entity.get("vector")
                if raw is None:
                    continue
                vec = np.array(raw, dtype=np.float32) if isinstance(raw, list) else np.frombuffer(raw, dtype=np.float32)
                if rid not in rid_vecs:
                    rid_vecs[rid] = vec.copy()
                    rid_counts[rid] = 1
                else:
                    rid_vecs[rid] += vec
                    rid_counts[rid] += 1
            with Session(sync_engine) as session:
                for rid, vec_sum in rid_vecs.items():
                    avg = (vec_sum / rid_counts[rid]).astype(np.float32)
                    blob = avg.tobytes()
                    existing = session.query(DocEmbeddingTable).filter(
                        DocEmbeddingTable.resource_id == rid).first()
                    if existing:
                        existing.embedding = blob
                        existing.chunk_count = rid_counts[rid]
                        existing.updated_at = __import__("datetime").datetime.utcnow()
                    else:
                        session.add(DocEmbeddingTable(
                            resource_id=rid, embedding=blob,
                            dims=len(avg), chunk_count=rid_counts[rid]))
                session.commit()
        except Exception as e:
            logger.warning(f"DocEmbeddingTable sync failed (non-fatal): {e}")


def add_link_content_to_vector_store(
        text_content, source, title, link_id, username, user_id=None):

    texts = chunk_link_content(text_content)

    documents = [
        Document(
            page_content=f"{title}\n\n{text}",
            metadata={
                "source": source,
                "page": f"{i+1}",
                "title": title,
                "belongs_to": username,
                "user_id": str(user_id) if user_id is not None else None,
                "link_id": f"{link_id}",
                "resource_id": str(link_id) if link_id is not None else None,
                "source_type": SourceType.LINK
            }
        ) for i, text in enumerate(texts)
    ]

    add_documents(documents)
    logger.info(f"processed: {source} with {title}")


def add_uploaded_document_content_to_vector_store(
        file_path, file_name, file_url, file_id, username, user_id=None):

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
                "user_id": str(user_id) if user_id is not None else None,
                "file_id": f"{file_id}",
                "resource_id": str(file_id) if file_id is not None else None,
                "source_type": source_type
            }
        ) for content_dict in texts
    ]

    add_documents(documents)
    logger.info(f"processed: {file_name} with id={file_id}")


def fetch_documents(
        include_selected,
        exclude_selected,
        window_size,
        username,
        prompt,
        source_type=None,
        user_id=None):

    if source_type == 'link':
        window_size_modified = window_size * settings.WINDOW_SIZE_MULTIPLIER
    else:
        window_size_modified = window_size

    # Open the table
    table = db.open_table(TABLE_NAME)
    names = _schema_names(table)

    # Generate embedding for the query
    query_embedding = embeddings.embed_query(prompt)

    # Build filter expression for LanceDB
    # Prefer stable user_id when column exists; keep belongs_to for legacy rows
    # NOTE: LanceDB 0.21.2 has a bug where string `= 'value'` returns 0 rows;
    # `LIKE '%value%'` works. Use LIKE as a workaround (safe for integer-string IDs).
    if user_id is not None and "user_id" in names:
        uid = _escape_filter_value(str(user_id))
        email = _escape_filter_value(username)
        # Use LIKE workaround for LanceDB 0.21.2 string comparison bug
        filter_conditions = [
            f"(user_id LIKE '%{uid}%' OR belongs_to = '{email}')"
        ]
    else:
        filter_conditions = [f"belongs_to = '{_escape_filter_value(username)}'"]

    # Handle exclude_selected sources
    if exclude_selected and len(exclude_selected) > 0:
        exclude_conditions = []
        for source in exclude_selected:
            exclude_conditions.append(
                f"source != '{_escape_filter_value(source)}'"
            )

        if exclude_conditions:
            filter_conditions.append(
                "(" + " AND ".join(exclude_conditions) + ")")

    # Handle include_selected sources
    if include_selected and len(include_selected) > 0:
        include_conditions = []
        for source in include_selected:
            include_conditions.append(
                f"source = '{_escape_filter_value(source)}'"
            )

        if include_conditions:
            filter_conditions.append(
                "(" + " OR ".join(include_conditions) + ")")

    # Handle source_type filter
    if source_type is not None:
        filter_conditions.append(
            f"source_type = '{_escape_filter_value(source_type)}'"
        )

    # Combine all filter conditions
    filter_expr = " AND ".join(filter_conditions)

    logger.info(f"LanceDB filter expression: {filter_expr}")

    # Perform similarity search
    search_results = table.search(
        query_embedding,
        vector_column_name="vector"
    ).where(filter_expr).limit(window_size_modified).to_pandas()

    # Process search results
    docs_with_scores = []
    for _, row in search_results.iterrows():
        # Create metadata dictionary
        metadata = {k: v for k, v in row.items()
                    if k not in ['vector', 'page_content'] and v is not None}

        # Create Document object
        doc = Document(
            page_content=row['page_content'],
            metadata=metadata
        )

        # Add to results with score (already in cosine similarity format)
        docs_with_scores.append((doc, row['_distance']))

    logger.info(f"Found {len(docs_with_scores)} relevant documents")
    return docs_with_scores


def fetch_documents_keyword(
        include_selected,
        exclude_selected,
        window_size,
        username,
        prompt,
        source_type=None,
        user_id=None):
    """Fallback keyword search for Hybrid Y1"""
    if source_type == 'link':
        window_size_modified = window_size * settings.WINDOW_SIZE_MULTIPLIER
    else:
        window_size_modified = window_size

    table = db.open_table(TABLE_NAME)
    names = _schema_names(table)

    if user_id is not None and "user_id" in names:
        uid = _escape_filter_value(str(user_id))
        email = _escape_filter_value(username)
        filter_conditions = [
            f"(user_id LIKE '%{uid}%' OR belongs_to = '{email}')"
        ]
    else:
        filter_conditions = [f"belongs_to = '{_escape_filter_value(username)}'"]

    if exclude_selected and len(exclude_selected) > 0:
        exclude_conditions = [f"source != '{_escape_filter_value(s)}'" for s in exclude_selected]
        filter_conditions.append("(" + " AND ".join(exclude_conditions) + ")")

    if include_selected and len(include_selected) > 0:
        include_conditions = [f"source = '{_escape_filter_value(s)}'" for s in include_selected]
        filter_conditions.append("(" + " OR ".join(include_conditions) + ")")

    if source_type is not None:
        filter_conditions.append(f"source_type = '{_escape_filter_value(source_type)}'")

    # Keyword condition (simple LIKE on title, filename, page_content)
    # Strip whitespace and escape SQL LIKE wildcards % and _
    clean_prompt = _escape_filter_value(prompt.strip())
    clean_prompt = clean_prompt.replace("%", "\\%").replace("_", "\\_")
    
    kw_conditions = []
    for term in clean_prompt.split():
        if term:
            # We don't have standard ESCAPE in lance sql string easily if it doesn't support it, 
            # but usually it's fine. Wait, does lance datafusion support ESCAPE? 
            # Actually, simply stripping them or replacing them is safer if ESCAPE '\' fails.
            # Let's just remove % and _ from the prompt entirely to be safe and avoid injection.
            safe_term = term.replace("\\%", "").replace("\\_", "")
            if safe_term:
                kw_conditions.append(f"(page_content LIKE '%{safe_term}%' OR title LIKE '%{safe_term}%' OR filename LIKE '%{safe_term}%')")
    
    if kw_conditions:
        filter_conditions.append("(" + " AND ".join(kw_conditions) + ")")
    else:
        # If no valid terms, return empty
        return []

    filter_expr = " AND ".join(filter_conditions)
    logger.info(f"LanceDB Keyword filter expression: {filter_expr}")

    search_results = table.search(None).where(filter_expr).limit(window_size_modified).to_pandas()

    docs_with_scores = []
    for _, row in search_results.iterrows():
        metadata = {k: v for k, v in row.items() if k not in ['vector', 'page_content'] and v is not None}
        doc = Document(page_content=row['page_content'], metadata=metadata)
        # Keyword matches get a fixed "distance" (0.0 means perfect match in distance terms)
        # We just need them ordered, we'll assign 0.0, the RRF will rely on their position
        docs_with_scores.append((doc, 0.0))

    return docs_with_scores

def fetch_documents_by_resource(resource_id: int, source_type: str, user_id=None, username=None):
    """
    Fetch chunks from LanceDB by resource_id (or fallback to file_id/link_id for old data).
    Returns: list of (Document, score) where score = 0.0
    """
    try:
        table = db.open_table(TABLE_NAME)
        names = _schema_names(table)
        
        filter_conditions = []
        if user_id is not None and "user_id" in names:
            uid = _escape_filter_value(str(user_id))
            email = _escape_filter_value(username) if username else ""
            if email:
                filter_conditions.append(f"(user_id LIKE '%{uid}%' OR belongs_to = '{email}')")
            else:
                filter_conditions.append(f"user_id LIKE '%{uid}%'")
        elif username:
            filter_conditions.append(f"belongs_to = '{_escape_filter_value(username)}'")
            
        rid = _escape_filter_value(str(resource_id))
        
        fallback = ""
        if source_type == "link" and "link_id" in names:
            fallback = f" OR link_id LIKE '%{rid}%'"
        elif source_type in ("file", "note") and "file_id" in names:
            # Notes and files both fell back to file_id in some legacy structures, or just file_id for file
            fallback = f" OR file_id LIKE '%{rid}%'"
            
        if "resource_id" in names:
            res_cond = f"(resource_id LIKE '%{rid}%'{fallback})"
        else:
            if fallback:
                res_cond = fallback[4:] # strip " OR "
            else:
                # No way to filter
                return []
                
        filter_conditions.append(res_cond)
        
        if source_type and "source_type" in names:
            filter_conditions.append(f"source_type = '{source_type}'")
            
        filter_expr = " AND ".join(filter_conditions)
        logger.info(f"LanceDB fetch_by_resource filter: {filter_expr}")
        
        # limit(1000) is just a safety cap for chunks per resource
        search_results = table.search(None).where(filter_expr).limit(1000).to_pandas()
        
        docs_with_scores = []
        for _, row in search_results.iterrows():
            metadata = {k: v for k, v in row.items() if k not in ['vector', 'page_content'] and v is not None}
            doc = Document(page_content=row['page_content'], metadata=metadata)
            docs_with_scores.append((doc, 0.0))
            
        return docs_with_scores
    except Exception as e:
        logger.error(f"Error fetching documents by resource: {e}")
        return []



def remove_documents(filename, username):
    try:
        # Open the table
        table = db.open_table(TABLE_NAME)

        # Build filter expression for LanceDB
        filter_expr = f"filename = '{_escape_filter_value(filename)}' AND belongs_to = '{_escape_filter_value(username)}'"

        # Get count before deletion for reporting
        count_before = table.count_rows(filter_expr)

        # Delete documents matching the filter
        table.delete(filter_expr)

        if count_before > 0:
            logger.info(
                f"Removed {count_before} documents with filename={filename} belonging to user={username}")
                
            # Sync remove to FTS5
            try:
                from backend.database import sync_engine
                from backend.core.fts5_utils import delete_by_filename
                with sync_engine.connect() as conn:
                    raw_conn = conn.connection.dbapi_connection
                    delete_by_filename(raw_conn, filename, belongs_to=username)
            except Exception as e:
                logger.error(f"FTS dual remove failed in remove_documents: {e}")
                
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
        # Open the table
        table = db.open_table(TABLE_NAME)

        # Build filter expression for LanceDB
        filter_expr = f"link_id = '{_escape_filter_value(link_id)}' AND belongs_to = '{_escape_filter_value(username)}'"

        # Get count before deletion for reporting
        count_before = table.count_rows(filter_expr)

        # Delete documents matching the filter
        table.delete(filter_expr)

        if count_before > 0:
            logger.info(
                f"Removed {count_before} documents with filename={link_id} belonging to user={username}")
                
            # Sync remove to FTS5
            try:
                from backend.database import sync_engine
                from backend.core.fts5_utils import delete_by_link_id
                with sync_engine.connect() as conn:
                    raw_conn = conn.connection.dbapi_connection
                    delete_by_link_id(raw_conn, link_id, belongs_to=username)
            except Exception as e:
                logger.error(f"FTS dual remove failed in remove_link_documents: {e}")
                
            return True
        else:
            logger.warning(
                f"No documents found with filename={link_id} belonging to user={username}")
            return False

    except Exception as err:
        logger.error(
            f"Error removing documents with filename={link_id}: {str(err)}")
        return False
