import argparse
import sys
import os
import pandas as pd
from backend.core.logging import get_logger
from backend.config import settings

# Must be run from project root, ensure imports work
sys.path.append(os.getcwd())

logger = get_logger()

def _get_lancedb_data(limit=None):
    from backend.vector_store.lance_db import db, TABLE_NAME
    table = db.open_table(TABLE_NAME)
    if limit:
        return table.search().limit(limit).to_pandas()
    return table.to_pandas()

def _get_chroma_data(limit=None):
    from backend.vector_store.chroma_db import vector_store
    collection = vector_store._collection
    # Get all documents
    result = collection.get()
    
    rows = []
    for i in range(len(result['ids'])):
        meta = result['metadatas'][i] if result['metadatas'] else {}
        row = {
            "id": result['ids'][i],
            "page_content": result['documents'][i],
        }
        row.update(meta)
        rows.append(row)
        if limit and len(rows) >= limit:
            break
    return pd.DataFrame(rows)

def _get_milvus_data(limit=None):
    from backend.vector_store.milvus_db import milvus_client, COLLECTION_NAME
    # Milvus query to get all items
    res = milvus_client.query(
        collection_name=COLLECTION_NAME,
        filter="id != ''",
        output_fields=["id", "page_content", "title", "filename", "user_id", "belongs_to", "source_type", "link_id"],
        limit=limit if limit else 16384 # milvus query limit max is 16384 usually
    )
    return pd.DataFrame(res)

def backfill(dry_run: bool = False, limit: int = None):
    try:
        from backend.database import sync_engine
        from backend.core.fts5_utils import insert_fts5
        import sqlite3
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        sys.exit(1)

    backend = getattr(settings, "DEFAULT_VECTOR_DB", "lancedb").lower()
    
    print(f"Starting FTS5 backfill from vector backend '{backend}'")
    logger.info(f"Starting FTS5 backfill from vector backend '{backend}'")
    
    try:
        if backend == "lancedb" or backend == "lance_db":
            df = _get_lancedb_data(limit)
        elif backend == "chroma" or backend == "chromadb":
            df = _get_chroma_data(limit)
        elif backend == "milvus" or backend == "milvus_lite":
            df = _get_milvus_data(limit)
        else:
            logger.error(f"Unsupported backend {backend}")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error fetching data from vector store: {e}")
        sys.exit(1)

    total_rows = len(df) if df is not None else 0
    print(f"Found {total_rows} rows to process in {backend}.")
    logger.info(f"Found {total_rows} rows to process in {backend}.")

    if total_rows == 0:
        print("Nothing to backfill.")
        logger.info("Nothing to backfill.")
        return

    inserted_count = 0
    skipped_count = 0
    error_count = 0

    if dry_run:
        print("DRY RUN mode. No data will be written to FTS5.")
        logger.info("DRY RUN mode. No data will be written to FTS5.")

    with sync_engine.connect() as conn:
        raw_conn = conn.connection.dbapi_connection
        try:
            # Check if table exists
            try:
                raw_conn.execute("SELECT 1 FROM chunks_fts LIMIT 1")
            except sqlite3.OperationalError:
                if not dry_run:
                    logger.info("chunks_fts table not found, creating...")
                    from backend.core.fts5_utils import create_fts5_table
                    create_fts5_table(raw_conn)

            for i, row in df.iterrows():
                chunk_id = row.get("id")
                if not chunk_id:
                    skipped_count += 1
                    continue
                    
                title = row.get("title", "")
                filename = row.get("filename", "")
                page_content = row.get("page_content", "")
                user_id = row.get("user_id", None)
                belongs_to = row.get("belongs_to", None)
                source_type = row.get("source_type", "")
                link_id = row.get("link_id", None)
                
                if user_id is None and belongs_to is None:
                    logger.warning(f"Row {chunk_id} has no user_id or belongs_to. Skipping to avoid cross-tenant leakage.")
                    skipped_count += 1
                    continue

                if not dry_run:
                    try:
                        # Check if already exists to prevent duplicate chunk_id
                        cursor = raw_conn.cursor()
                        cursor.execute("SELECT 1 FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
                        if cursor.fetchone() is not None:
                            skipped_count += 1
                            continue

                        insert_fts5(
                            raw_conn,
                            chunk_id=chunk_id,
                            title=title,
                            filename=filename,
                            page_content=page_content,
                            user_id=user_id,
                            source_type=source_type,
                            link_id=link_id,
                            belongs_to=belongs_to
                        )
                        inserted_count += 1
                        
                        if inserted_count % 100 == 0:
                            print(f"Progress: inserted {inserted_count} rows...")
                            logger.info(f"Progress: inserted {inserted_count} rows...")
                            
                    except Exception as e:
                        print(f"Error inserting chunk_id {chunk_id}: {e}")
                        logger.error(f"Error inserting chunk_id {chunk_id}: {e}")
                        error_count += 1
                else:
                    inserted_count += 1

        finally:
            pass # context manager handles close if possible, or leave it

    print(f"Backfill complete! Processed {total_rows} total rows.")
    print(f"Inserted: {inserted_count}, Skipped (duplicate/invalid): {skipped_count}, Errors: {error_count}")
    logger.info(f"Backfill complete! Processed {total_rows} total rows.")
    logger.info(f"Inserted: {inserted_count}, Skipped (duplicate/invalid): {skipped_count}, Errors: {error_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill FTS5 chunks_fts table from Vector Store.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without writing.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows to process.")
    
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, limit=args.limit)
