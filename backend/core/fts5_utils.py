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
                try:
                    cursor.execute("""
                    INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                           user_id, belongs_to, source_type, link_id)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """, (chunk_id, title, filename, page_content, user_id, belongs_to,
                         source_type, link_id))
                except Exception:
                    raise op_e
        conn.commit()
    except Exception as e:
        logger.error(f"Error inserting into chunks_fts: {e}")

def insert_fts5_batch(conn: sqlite3.Connection, rows: list):
    """Batch insert chunks into chunks_fts with a single commit to prevent fsync storms."""
    if not rows:
        return
    try:
        cursor = conn.cursor()
        param_rows = [
            (
                r.get("chunk_id"),
                r.get("title") or "",
                r.get("filename") or "",
                r.get("page_content") or "",
                str(r.get("user_id")) if r.get("user_id") is not None else None,
                r.get("belongs_to") or "",
                str(r.get("source_type")) if r.get("source_type") is not None else "",
                str(r.get("link_id")) if r.get("link_id") is not None else None,
                str(r.get("resource_id")) if r.get("resource_id") is not None else None,
            )
            for r in rows
        ]
        try:
            cursor.executemany("""
            INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                   user_id, belongs_to, source_type, link_id, resource_id)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, param_rows)
        except sqlite3.OperationalError as op_e:
            msg = str(op_e).lower()
            if "no such table" in msg:
                create_fts5_table(conn)
                cursor.executemany("""
                INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                       user_id, belongs_to, source_type, link_id, resource_id)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, param_rows)
            elif "no such column" in msg:
                param_rows_no_res = [row[:8] for row in param_rows]
                cursor.executemany("""
                INSERT INTO chunks_fts(chunk_id, title, filename, page_content,
                                       user_id, belongs_to, source_type, link_id)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """, param_rows_no_res)
            else:
                raise op_e
        conn.commit()
    except Exception as e:
        logger.error(f"Error in insert_fts5_batch: {e}")

def match_fts5(conn: sqlite3.Connection, prompt: str, user_id=None,
               belongs_to=None, limit=50, include_sources=None, source_type=None):
    """BM25 search via FTS5, with user isolation and optional source filtering.
    Falls back to parameterized substring LIKE matching when FTS5 trigram returns 0 rows
    (e.g. 2-character Chinese keywords where trigram produces no tokens).
    """
    terms = _sanitize_fts_query(prompt)
    rows = []
    cursor = conn.cursor()

    if terms:
        where_parts = ["chunks_fts MATCH ?"]
        params = [terms]

        if user_id is not None:
            where_parts.append("user_id = ?")
            params.append(str(user_id))
        if belongs_to is not None:
            where_parts.append("belongs_to = ?")
            params.append(belongs_to)
        if source_type is not None:
            where_parts.append("source_type = ?")
            params.append(str(source_type))
        if include_sources and len(include_sources) > 0:
            clean_sources = [str(s) for s in include_sources if s]
            if clean_sources:
                placeholders = ",".join("?" for _ in clean_sources)
                where_parts.append(f"(filename IN ({placeholders}) OR title IN ({placeholders}))")
                params.extend(clean_sources * 2)

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
                logger.warning(f"FTS5 match error: {e}")
                rows = []

    # Fallback to parameterized substring search if FTS5 matched nothing
    if not rows and prompt and prompt.strip():
        cleaned_words = [w.strip() for w in re.sub(r'[^\w\u4e00-\u9fff]', ' ', prompt).split() if w.strip()]
        if cleaned_words:
            fallback_where = []
            fallback_params = []

            term_conditions = []
            for w in cleaned_words[:5]:
                term_conditions.append("(page_content LIKE ? OR title LIKE ? OR filename LIKE ?)")
                fallback_params.extend([f"%{w}%", f"%{w}%", f"%{w}%"])
            fallback_where.append("(" + " OR ".join(term_conditions) + ")")

            if user_id is not None:
                fallback_where.append("user_id = ?")
                fallback_params.append(str(user_id))
            if belongs_to is not None:
                fallback_where.append("belongs_to = ?")
                fallback_params.append(belongs_to)
            if source_type is not None:
                fallback_where.append("source_type = ?")
                fallback_params.append(str(source_type))
            if include_sources and len(include_sources) > 0:
                clean_sources = [str(s) for s in include_sources if s]
                if clean_sources:
                    placeholders = ",".join("?" for _ in clean_sources)
                    fallback_where.append(f"(filename IN ({placeholders}) OR title IN ({placeholders}))")
                    fallback_params.extend(clean_sources * 2)

            f_where = " AND ".join(fallback_where)
            f_sql = f"""
            SELECT chunk_id, title, filename, page_content, user_id,
                   belongs_to, source_type, link_id, resource_id,
                   -1.0 AS bm25_score
            FROM chunks_fts
            WHERE {f_where}
            LIMIT ?
            """
            fallback_params.append(limit)
            try:
                cursor.execute(f_sql, fallback_params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError as e:
                if "no such column" in str(e).lower() and "resource_id" in str(e).lower():
                    f_sql = f_sql.replace(", resource_id", "")
                    cursor.execute(f_sql, fallback_params)
                    rows = cursor.fetchall()
                else:
                    logger.warning(f"FTS5 fallback search error: {e}")

    if not rows:
        return []

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
