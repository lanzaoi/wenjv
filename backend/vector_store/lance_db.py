from langchain_ollama import OllamaEmbeddings
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
embeddings = OllamaEmbeddings(
    model=settings.EMBEDDINGS_MODEL, base_url=settings.OLLAMA_HOST)

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
            pa.field("source_type", pa.string())
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

        # Try a few common Lance APIs across versions
        errors = []
        attempts = [
            lambda: table.create_index(
                metric="cosine",
                vector_column_name="vector",
                index_type="IVF_PQ",
                num_partitions=min(256, max(2, n // 40)),
                num_sub_vectors=min(96, max(8, settings.EMBEDDINGS_DIMENSION // 4)),
            ),
            lambda: table.create_index(
                metric="cosine",
                vector_column_name="vector",
            ),
            lambda: table.create_index("vector"),
        ]
        for fn in attempts:
            try:
                fn()
                logger.info(f"vector ANN index ensured on {TABLE_NAME} (rows={n})")
                return True
            except Exception as e:
                errors.append(str(e))
        logger.warning(f"vector index not created: {errors[-1] if errors else 'unknown'}")
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
                      "link_id", "file_id", "source_type", "user_id"]:
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
    if user_id is not None and "user_id" in names:
        uid = _escape_filter_value(str(user_id))
        email = _escape_filter_value(username)
        filter_conditions = [
            f"(user_id = '{uid}' OR (user_id IS NULL AND belongs_to = '{email}') OR belongs_to = '{email}')"
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
                    if k not in ['vector', 'page_content', 'id'] and v is not None}

        # Create Document object
        doc = Document(
            page_content=row['page_content'],
            metadata=metadata
        )

        # Add to results with score (already in cosine similarity format)
        docs_with_scores.append((doc, row['_distance']))

    logger.info(f"Found {len(docs_with_scores)} relevant documents")
    return docs_with_scores


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
            return True
        else:
            logger.warning(
                f"No documents found with filename={link_id} belonging to user={username}")
            return False

    except Exception as err:
        logger.error(
            f"Error removing documents with filename={link_id}: {str(err)}")
        return False
