from __future__ import annotations
from typing import Optional, List, Dict, Tuple, Any
from backend.core.embedder import get_embedder
try:
    from langchain.schema import Document
except ImportError:
    from langchain_core.documents import Document
import lancedb
import threading
import uuid
from backend.config import settings
from backend.core.logging import get_logger
from backend.core.utils import (
    chunk_link_content,
    load_and_chunk_document,
)
from backend.api.models import SourceType
import pyarrow as pa


from backend.core.embedding_cache import CachedEmbedder
from backend.core.micro_batch_embedder import MicroBatchEmbedder

logger = get_logger()

# Initialize embeddings wrapped with cache and micro-batch aggregator
embeddings = MicroBatchEmbedder(
    CachedEmbedder(get_embedder()),
    batch_size=getattr(settings, "INGESTION_MICRO_BATCH_SIZE", 32),
    timeout_ms=getattr(settings, "INGESTION_MICRO_BATCH_TIMEOUT_MS", 50),
)

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
            pa.field("chunk_order", pa.int32()),
            pa.field("image_path", pa.string()),
        ])

        # Create empty table with schema
        db.create_table(TABLE_NAME, schema=schema)

        table = db.open_table(TABLE_NAME)

        # Scalar indexes for metadata filters
        for col in ("belongs_to", "user_id", "source_type", "source", "filename", "link_id", "resource_id"):
            try:
                table.create_scalar_index(col, index_type="BTREE")
            except Exception as e:
                logger.warning(f"scalar index on {col}: {e}")
        logger.info(f"Created new LanceDB table: {TABLE_NAME}")
    else:
        table = db.open_table(TABLE_NAME)
        # Ensure image_path column exists for backwards compatibility
        cols = getattr(table.schema, "names", [])
        if "image_path" not in cols:
            try:
                if hasattr(table, "add_columns"):
                    table.add_columns({"image_path": "cast(null as string)"})
                    logger.info("Migrated LanceDB schema: added image_path column")
            except Exception as e:
                logger.warning(f"Failed to add image_path column to {TABLE_NAME}: {e}")
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

        # If a vector index already exists and unindexed rows are small, skip costly rebuild
        try:
            existing_indices = table.list_indices() if hasattr(table, "list_indices") else []
            for idx in existing_indices:
                cols = getattr(idx, "columns", []) or []
                if "vector" in cols:
                    unindexed = getattr(idx, "num_unindexed_rows", 0) or 0
                    if unindexed < 1000:
                        logger.debug(f"skip vector index rebuild: unindexed={unindexed} (<1000)")
                        return True
        except Exception as idx_err:
            logger.debug(f"index inspection fallback: {idx_err}")

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


VISUAL_TABLE_NAME = "visual_store"
VISUAL_DIM = int(getattr(settings, "VISUAL_EMBEDDING_DIMENSION", 768) or 768)


def initialize_visual_collection():
    tbl_names = db.table_names() if hasattr(db, "table_names") else db.list_tables()
    need_create = VISUAL_TABLE_NAME not in tbl_names

    if not need_create:
        try:
            table = db.open_table(VISUAL_TABLE_NAME)
            vec_field = table.schema.field("vector")
            curr_dim = getattr(vec_field.type, "list_size", None)
            if curr_dim is not None and curr_dim != VISUAL_DIM:
                logger.info(f"Visual table dimension mismatch: {curr_dim} != {VISUAL_DIM}. Dropping and recreating {VISUAL_TABLE_NAME}")
                db.drop_table(VISUAL_TABLE_NAME)
                need_create = True
        except Exception as e:
            logger.warning(f"Error checking visual table schema: {e}")

    if need_create:
        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), VISUAL_DIM)),
            pa.field("page_content", pa.string()),
            pa.field("image_path", pa.string()),
            pa.field("source", pa.string()),
            pa.field("page", pa.string()),
            pa.field("title", pa.string()),
            pa.field("filename", pa.string()),
            pa.field("belongs_to", pa.string()),
            pa.field("user_id", pa.string()),
            pa.field("file_id", pa.string()),
            pa.field("resource_id", pa.string()),
            pa.field("source_type", pa.string()),
        ])
        db.create_table(VISUAL_TABLE_NAME, schema=schema)
        table = db.open_table(VISUAL_TABLE_NAME)
        for col in ("belongs_to", "user_id", "source_type", "filename", "resource_id"):
            try:
                table.create_scalar_index(col, index_type="BTREE")
            except Exception as e:
                logger.warning(f"visual scalar index on {col}: {e}")
        logger.info(f"Created new LanceDB visual table: {VISUAL_TABLE_NAME} (dimension={VISUAL_DIM})")
    else:
        logger.info(f"Using existing LanceDB visual table: {VISUAL_TABLE_NAME} (dimension={VISUAL_DIM})")


# Initialize tables
initialize_collection()
initialize_visual_collection()

# Exclusive persistence lock for LanceDB + SQLite FTS5 / ChunkMapping dual-writes
_lance_write_lock = threading.Lock()


def add_documents(documents):
    """Add documents to the LanceDB vector store"""
    if not documents:
        return

    # 1. Generate embeddings concurrently (outside lock so MicroBatchEmbedder aggregates across documents)
    texts_to_embed = [doc.metadata.get("indexing_text") or doc.page_content for doc in documents]
    embeddings_list = embeddings.embed_documents(texts_to_embed)

    # 2. Persist to LanceDB and SQLite under exclusive single-writer lock
    with _lance_write_lock:
        table = db.open_table(TABLE_NAME)
        names = _schema_names(table)

        # Prepare data for LanceDB
        data = []
        for i, (doc, embedding) in enumerate(zip(documents, embeddings_list)):
            # Prefer deterministic chunk_id if present
            doc_id = str(doc.metadata.get("id") or doc.metadata.get("chunk_id") or uuid.uuid4())

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
                          "chunk_group", "chunk_order", "image_path"]:
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

        # Sync to FTS5 via batch insert
        try:
            from backend.database import sync_engine
            from backend.core.fts5_utils import insert_fts5_batch
            with sync_engine.connect() as conn:
                raw_conn = conn.connection.dbapi_connection
                fts_rows = [
                    {
                        "chunk_id": entity["id"],
                        "title": entity.get("title", ""),
                        "filename": entity.get("filename", ""),
                        "page_content": doc.metadata.get("indexing_text") or entity.get("page_content", ""),
                        "user_id": entity.get("user_id"),
                        "source_type": entity.get("source_type", ""),
                        "link_id": entity.get("link_id"),
                        "belongs_to": entity.get("belongs_to", ""),
                        "resource_id": entity.get("resource_id"),
                    }
                    for entity, doc in zip(data, documents)
                ]
                insert_fts5_batch(raw_conn, fts_rows)
        except Exception as e:
            logger.error(f"FTS dual write failed in add_documents: {e}")

        # Sync to ChunkMappingTable for small-to-large retrieval (batch query + add_all)
        try:
            from backend.database import sync_engine, ChunkMappingTable
            from sqlalchemy.orm import Session
            with Session(sync_engine) as session:
                candidate_entities = [
                    entity for entity in data
                    if entity.get("chunk_group") is not None and entity.get("chunk_order") is not None
                ]
                if candidate_entities:
                    cids = [e["id"] for e in candidate_entities]
                    existing_cids = set(
                        row[0] for row in session.query(ChunkMappingTable.chunk_id).filter(
                            ChunkMappingTable.chunk_id.in_(cids)
                        ).all()
                    )
                    mappings_to_add = [
                        ChunkMappingTable(
                            chunk_id=entity["id"],
                            chunk_group=str(entity["chunk_group"]),
                            chunk_order=int(entity["chunk_order"]),
                            resource_id=entity.get("resource_id", ""),
                        )
                        for entity in candidate_entities
                        if entity["id"] not in existing_cids
                    ]
                    if mappings_to_add:
                        session.add_all(mappings_to_add)
                        session.commit()
        except Exception as e:
            logger.warning(f"ChunkMappingTable sync failed (non-fatal): {e}")

        # Sync to DocEmbeddingTable for late chunking
        if getattr(settings, "LATE_CHUNKING_ENABLED", False):
            try:
                from backend.database import sync_engine, DocEmbeddingTable
                from sqlalchemy.orm import Session
                import numpy as np
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
        file_path, file_name, file_url, file_id, username, user_id=None, parsed_chunks=None):

    texts = load_and_chunk_document(
        file_path,
        resource_id=str(file_id) if file_id is not None else None,
        parsed_chunks=parsed_chunks,
    )

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
            "source_type": source_type,
            "id": content_dict.get("id"),
            "chunk_id": content_dict.get("chunk_id"),
            "chunk_group": content_dict.get("chunk_group"),
            "chunk_order": content_dict.get("chunk_order"),
            "indexing_text": content_dict.get("indexing_text"),
            "start_char": content_dict.get("start_char"),
            "end_char": content_dict.get("end_char"),
            "header_str": content_dict.get("header_str"),
            "image_path": content_dict.get("image_path"),
        }
        documents.append(Document(page_content=content_dict['text'], metadata=meta))

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
    if user_id is not None and "user_id" in names:
        uid = _escape_filter_value(str(user_id))
        email = _escape_filter_value(username)
        filter_conditions = [
            f"(user_id = '{uid}' OR belongs_to = '{email}')"
        ]
    else:
        filter_conditions = [f"belongs_to = '{_escape_filter_value(username)}'"]

    # Handle exclude_selected sources
    if exclude_selected and len(exclude_selected) > 0:
        exclude_conditions = []
        for source in exclude_selected:
            s_esc = _escape_filter_value(source)
            if "filename" in names and "title" in names:
                exclude_conditions.append(
                    f"(source != '{s_esc}' AND filename != '{s_esc}' AND title != '{s_esc}')"
                )
            else:
                exclude_conditions.append(f"source != '{s_esc}'")

        if exclude_conditions:
            filter_conditions.append(
                "(" + " AND ".join(exclude_conditions) + ")")

    # Handle include_selected sources
    if include_selected and len(include_selected) > 0:
        include_conditions = []
        for source in include_selected:
            s_esc = _escape_filter_value(source)
            if "filename" in names and "title" in names:
                include_conditions.append(
                    f"(source = '{s_esc}' OR filename = '{s_esc}' OR title = '{s_esc}')"
                )
            else:
                include_conditions.append(f"source = '{s_esc}'")

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

    # Build search query with projected columns (excluding vector column, including _distance)
    select_cols = [c for c in names if c != "vector"]
    if "_distance" not in select_cols:
        select_cols.append("_distance")

    search_builder = table.search(
        query_embedding,
        vector_column_name="vector"
    )
    try:
        search_results = search_builder.where(filter_expr, prefilter=True).select(select_cols).limit(window_size_modified).to_list()
    except TypeError:
        search_results = search_builder.where(filter_expr).select(select_cols).limit(window_size_modified).to_list()
    except Exception:
        search_results = search_builder.where(filter_expr).limit(window_size_modified).to_list()

    # Process search results
    docs_with_scores = []
    for row in search_results:
        content = row.get("page_content") or ""
        metadata = {
            k: v for k, v in row.items()
            if k not in ("vector", "page_content", "_distance") and v is not None
        }
        doc = Document(
            page_content=content,
            metadata=metadata
        )
        score = row.get("_distance", 0.0)
        docs_with_scores.append((doc, score))

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
            f"(user_id = '{uid}' OR belongs_to = '{email}')"
        ]
    else:
        filter_conditions = [f"belongs_to = '{_escape_filter_value(username)}'"]

    if exclude_selected and len(exclude_selected) > 0:
        exclude_conditions = []
        for s in exclude_selected:
            s_esc = _escape_filter_value(s)
            if "filename" in names and "title" in names:
                exclude_conditions.append(f"(source != '{s_esc}' AND filename != '{s_esc}' AND title != '{s_esc}')")
            else:
                exclude_conditions.append(f"source != '{s_esc}'")
        if exclude_conditions:
            filter_conditions.append("(" + " AND ".join(exclude_conditions) + ")")

    if include_selected and len(include_selected) > 0:
        include_conditions = []
        for s in include_selected:
            s_esc = _escape_filter_value(s)
            if "filename" in names and "title" in names:
                include_conditions.append(f"(source = '{s_esc}' OR filename = '{s_esc}' OR title = '{s_esc}')")
            else:
                include_conditions.append(f"source = '{s_esc}'")
        if include_conditions:
            filter_conditions.append("(" + " OR ".join(include_conditions) + ")")

    if source_type is not None:
        filter_conditions.append(f"source_type = '{_escape_filter_value(source_type)}'")

    # Keyword condition (simple LIKE on title, filename, page_content)
    clean_prompt = _escape_filter_value(prompt.strip())
    kw_conditions = []
    for term in clean_prompt.split():
        # Remove literal wildcards to avoid uncontrolled wildcards in LIKE
        safe_term = term.replace("%", "").replace("_", "")
        if safe_term:
            kw_conditions.append(f"(page_content LIKE '%{safe_term}%' OR title LIKE '%{safe_term}%' OR filename LIKE '%{safe_term}%')")
    
    if kw_conditions:
        filter_conditions.append("(" + " AND ".join(kw_conditions) + ")")
    else:
        # If no valid terms, return empty
        return []

    filter_expr = " AND ".join(filter_conditions)
    logger.info(f"LanceDB Keyword filter expression: {filter_expr}")

    select_cols = [c for c in names if c != "vector"]
    search_builder = table.search(None)
    try:
        search_results = search_builder.where(filter_expr, prefilter=True).select(select_cols).limit(window_size_modified).to_list()
    except TypeError:
        search_results = search_builder.where(filter_expr).select(select_cols).limit(window_size_modified).to_list()
    except Exception:
        search_results = search_builder.where(filter_expr).limit(window_size_modified).to_list()

    docs_with_scores = []
    for row in search_results:
        metadata = {k: v for k, v in row.items() if k not in ('vector', 'page_content', '_distance') and v is not None}
        doc = Document(page_content=row.get('page_content') or '', metadata=metadata)
        # Keyword matches get a fixed "distance" (0.0 means perfect match in distance terms)
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
                filter_conditions.append(f"(user_id = '{uid}' OR belongs_to = '{email}')")
            else:
                filter_conditions.append(f"user_id = '{uid}'")
        elif username:
            filter_conditions.append(f"belongs_to = '{_escape_filter_value(username)}'")
            
        rid = _escape_filter_value(str(resource_id))
        
        fallback = ""
        if source_type == "link" and "link_id" in names:
            fallback = f" OR link_id = '{rid}'"
        elif source_type in ("file", "note") and "file_id" in names:
            fallback = f" OR file_id = '{rid}'"
            
        if "resource_id" in names:
            res_cond = f"(resource_id = '{rid}'{fallback})"
        else:
            if fallback:
                res_cond = fallback[4:] # strip " OR "
            else:
                return []
                
        filter_conditions.append(res_cond)
        
        if source_type and "source_type" in names:
            filter_conditions.append(f"source_type = '{source_type}'")
            
        filter_expr = " AND ".join(filter_conditions)
        logger.info(f"LanceDB fetch_by_resource filter: {filter_expr}")
        
        query = table.search(None).where(filter_expr).limit(1000)
        if hasattr(query, "to_list") and not hasattr(getattr(query, "to_pandas", None), "_mock_return_value"):
            try:
                select_cols = [c for c in names if c != "vector"]
                if hasattr(query, "select"):
                    query = query.select(select_cols)
                search_results = query.to_list()
            except Exception:
                search_results = query.to_pandas()
        else:
            search_results = query.to_pandas()

        docs_with_scores = []
        if hasattr(search_results, "iterrows"):
            for _, row in search_results.iterrows():
                metadata = {k: v for k, v in row.items() if k not in ['vector', 'page_content'] and v is not None}
                doc = Document(page_content=row['page_content'], metadata=metadata)
                docs_with_scores.append((doc, 0.0))
        else:
            for row in search_results:
                metadata = {k: v for k, v in row.items() if k not in ('vector', 'page_content', '_distance') and v is not None}
                doc = Document(page_content=row.get('page_content') or '', metadata=metadata)
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


def add_visual_documents(documents, image_bytes_list=None):
    """
    Add visual documents to the visual_store table.
    Visual embeddings (1024d) live in a separate vector space from text embeddings.
    """
    if not documents:
        return

    from backend.core.visual_embedder import get_visual_embedder
    embedder = get_visual_embedder()

    # 1. Generate visual embeddings
    if image_bytes_list and len(image_bytes_list) == len(documents):
        embeddings_list = embedder.embed_images(image_bytes_list)
    else:
        embeddings_list = []
        for doc in documents:
            img_path = doc.metadata.get("image_path")
            if img_path and os.path.exists(img_path):
                with open(img_path, "rb") as f:
                    embeddings_list.append(embedder.embed_image(f.read()))
            else:
                embeddings_list.append(embedder.embed_query_text(doc.page_content or ""))

    # 2. Persist to visual_store under exclusive writer lock
    with _lance_write_lock:
        table = db.open_table(VISUAL_TABLE_NAME)
        names = _schema_names(table)
        data = []
        for doc, emb in zip(documents, embeddings_list):
            doc_id = str(doc.metadata.get("id") or doc.metadata.get("chunk_id") or uuid.uuid4())
            entity = {
                "id": doc_id,
                "vector": emb,
                "page_content": doc.page_content or "",
                "image_path": doc.metadata.get("image_path") or "",
            }
            for k, v in doc.metadata.items():
                if k not in entity:
                    entity[k] = str(v) if k == "user_id" and v is not None else v

            for field in [
                "source", "page", "title", "filename", "belongs_to",
                "file_id", "source_type", "user_id", "resource_id"
            ]:
                if field not in entity:
                    entity[field] = None

            if names:
                entity = {k: v for k, v in entity.items() if k in names}
            data.append(entity)

        table.add(data)
        logger.info(f"Added {len(documents)} visual documents to {VISUAL_TABLE_NAME}")


def fetch_visual_documents(
    prompt: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    window_size: int = 5,
    username: str = "",
    user_id: Optional[int] = None,
    source_type: Optional[str] = None,
) -> List[Tuple[Any, float, str]]:
    """
    ANN vector search against visual_store table using either image or text query vector.
    """
    from backend.core.visual_embedder import get_visual_embedder
    embedder = get_visual_embedder()
    query_vector = embedder.embed_visual_query(text=prompt, image_bytes=image_bytes)

    table = db.open_table(VISUAL_TABLE_NAME)
    names = _schema_names(table)

    filter_conditions = []
    if user_id is not None and "user_id" in names:
        uid = _escape_filter_value(str(user_id))
        email = _escape_filter_value(username)
        filter_conditions.append(f"(user_id = '{uid}' OR belongs_to = '{email}')")
    elif username:
        filter_conditions.append(f"belongs_to = '{_escape_filter_value(username)}'")

    if source_type:
        filter_conditions.append(f"source_type = '{_escape_filter_value(source_type)}'")

    filter_expr = " AND ".join(filter_conditions) if filter_conditions else ""

    select_cols = [c for c in names if c != "vector"]
    if "_distance" not in select_cols:
        select_cols.append("_distance")

    search_builder = table.search(query_vector, vector_column_name="vector")
    try:
        if filter_expr:
            try:
                results = search_builder.where(filter_expr, prefilter=True).select(select_cols).limit(window_size).to_list()
            except Exception:
                results = search_builder.where(filter_expr).select(select_cols).limit(window_size).to_list()
        else:
            results = search_builder.select(select_cols).limit(window_size).to_list()
    except Exception as e:
        logger.warning(f"visual search failed: {e}")
        return []

    docs_with_scores = []
    for row in results:
        content = row.get("page_content") or ""
        metadata = {
            k: v for k, v in row.items()
            if k not in ("vector", "page_content", "_distance") and v is not None
        }
        doc = Document(page_content=content, metadata=metadata)
        score = float(row.get("_distance", 0.0))
        source = metadata.get("source") or metadata.get("filename") or "visual"
        docs_with_scores.append((doc, score, source))

    return docs_with_scores


def remove_visual_documents(resource_id: str, username: str = "", user_id: Optional[int] = None) -> bool:
    """Delete visual records matching resource_id under tenant safety guard."""
    try:
        table = db.open_table(VISUAL_TABLE_NAME)
        conditions = [f"(resource_id = '{_escape_filter_value(resource_id)}' OR file_id = '{_escape_filter_value(resource_id)}')"]
        if user_id is not None:
            conditions.append(f"(user_id = '{_escape_filter_value(str(user_id))}' OR belongs_to = '{_escape_filter_value(username)}')")
        elif username:
            conditions.append(f"belongs_to = '{_escape_filter_value(username)}'")
        filter_expr = " AND ".join(conditions)
        table.delete(filter_expr)
        return True
    except Exception as e:
        logger.warning(f"Failed to remove visual documents for resource {resource_id}: {e}")
        return False
