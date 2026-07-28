import sqlite3
import re
from backend.core.logging import get_logger

logger = get_logger()

def create_fts5_table(conn: sqlite3.Connection):
    try:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            chunk_id UNINDEXED,
            title,
            filename,
            page_content,
            user_id UNINDEXED,
            belongs_to UNINDEXED,
            source_type UNINDEXED,
            link_id UNINDEXED,
            resource_id UNINDEXED,
            tokenize='trigram'
        );
        """)
        conn.commit()
        logger.info("chunks_fts table created with trigram tokenizer.")
    except Exception as e:
        logger.error(f"Error creating chunks_fts table: {e}")

def insert_fts5(conn: sqlite3.Connection, chunk_id: str, title: str, filename: str,
                page_content: str, user_id: str, source_type: str,
                link_id: str = None, belongs_to: str = None, resource_id: str = None):
    try:
        title = title or ""
        filename = filename or ""
        page_content = page_content or ""
        
        cursor = conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                   user_id, belongs_to, source_type, link_id, resource_id)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (chunk_id, title, filename, page_content, user_id, belongs_to,
                 source_type, link_id, resource_id))
        except sqlite3.OperationalError:
            # Old schema without resource_id column — fall back
            cursor.execute("""
            INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                   user_id, belongs_to, source_type, link_id)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """, (chunk_id, title, filename, page_content, user_id, belongs_to,
                 source_type, link_id))
        except sqlite3.OperationalError as op_e:
            msg = str(op_e).lower()
            if "no such table" in msg:
                create_fts5_table(conn)
                cursor.execute("""
                INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                       user_id, belongs_to, source_type, link_id, resource_id)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (chunk_id, title, filename, page_content, user_id, belongs_to,
                      source_type, link_id, resource_id))
            elif "no such column" in msg:
                # Old table without resource_id column
                cursor.execute("""
                INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                       user_id, belongs_to, source_type, link_id)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """, (chunk_id, title, filename, page_content, user_id, belongs_to,
                      source_type, link_id))
            else:
                raise op_e
        conn.commit()
    except Exception as e:
        logger.error(f"Error inserting into chunks_fts: {e}")

def match_fts5(conn: sqlite3.Connection, prompt: str, user_id=None,
               belongs_to=None, limit=50):
    """BM25 search via FTS5, with user isolation."""
    terms = _sanitize_fts_query(prompt)
    if not terms:
        return []
    
    cursor = conn.cursor()
    where_parts = ["chunks_fts MATCH ?"]
    params = [terms]
    
    if user_id is not None:
        where_parts.append("user_id = ?")
        params.append(str(user_id))
    if belongs_to is not None:
        where_parts.append("belongs_to = ?")
        params.append(belongs_to)
    
    where = " AND ".join(where_parts)
    sql = f"""
    SELECT chunk_id, title, filename, page_content, user_id,
           belongs_to, source_type, link_id, resource_id,
           rank AS bm25_score
    FROM chunks_fts
    WHERE {where}
    ORDER BY rank
    LIMIT ?
    """
    params.append(limit)
    
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        if "no such column" in str(e).lower() and "resource_id" in str(e).lower():
            # Old table, retry without resource_id
            sql = sql.replace(", resource_id", "")
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        else:
            raise
    
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in rows]

def delete_by_chunk_id(conn: sqlite3.Connection, chunk_id: str):
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Error deleting from chunks_fts by chunk_id: {e}")

def delete_by_filename(conn: sqlite3.Connection, filename: str, belongs_to: str = None):
    try:
        cursor = conn.cursor()
        if belongs_to:
            cursor.execute(
                "DELETE FROM chunks_fts WHERE filename = ? AND belongs_to = ?",
                (filename, belongs_to))
        else:
            cursor.execute("DELETE FROM chunks_fts WHERE filename = ?", (filename,))
        conn.commit()
    except Exception as e:
        logger.error(f"Error in delete_by_filename: {e}")

def delete_by_link_id(conn: sqlite3.Connection, link_id: str, belongs_to: str = None):
    try:
        cursor = conn.cursor()
        if belongs_to:
            cursor.execute(
                "DELETE FROM chunks_fts WHERE link_id = ? AND belongs_to = ?",
                (link_id, belongs_to))
        else:
            cursor.execute("DELETE FROM chunks_fts WHERE link_id = ?", (link_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Error in delete_by_link_id: {e}")

def _sanitize_fts_query(text: str) -> str:
    """Clean text for FTS5 MATCH — char-by-char OR for CJK, word AND for ASCII."""
    # Remove FTS5 special chars but keep CJK and ASCII
    cleaned = re.sub(r'[^\w\u4e00-\u9fff]', ' ', text)
    words = [t for t in cleaned.split() if len(t) >= 1]

    if not words:
        return ""

    cjk_parts = []
    ascii_parts = []

    for word in words:
        if re.search(r'[\u4e00-\u9fff]', word):
            # Chinese: build 2- and 3-character sliding windows from CJK chars
            cjk_chars = re.findall(r'[\u4e00-\u9fff]', word)
            # n-grams of lengths 2 and 3
            for n in (3, 2):
                for i in range(len(cjk_chars) - n + 1):
                    cjk_parts.append(''.join(cjk_chars[i:i+n]))
            # Also include each single ASCII+number chunk
            chars = re.findall(r'[A-Za-z0-9]+', word)
            cjk_parts.extend(chars)
        else:
            ascii_parts.append(f'"{word}"')

    result_parts = []
    if cjk_parts:
        # Deduplicate CJK n-grams
        unique_grams = list(dict.fromkeys(cjk_parts))
        result_parts.append('(' + ' OR '.join(f'"{c}"' for c in unique_grams[:50]) + ')')  # cap at 50 terms
    if ascii_parts:
        result_parts.append('(' + ' AND '.join(ascii_parts) + ')')

    return ' AND '.join(result_parts) if result_parts else ""
