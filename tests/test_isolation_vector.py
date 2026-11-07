import pytest
import lancedb
from unittest.mock import patch
from langchain.schema import Document
import backend.vector_store.lance_db as lance_mod


def test_vector_side_isolation(tmp_path):
    """Test that LanceDB vector search strictly isolates documents by user_id and username."""
    # Connect to a fresh temp LanceDB directory
    temp_db = lancedb.connect(str(tmp_path / "lancedb_test_iso"))
    table_name = "test_vectors_iso"

    # Mock embeddings so we don't need network/Ollama/SiliconFlow calls during tests
    dummy_vec_a = [0.1] * lance_mod.settings.EMBEDDINGS_DIMENSION
    dummy_vec_b = [0.2] * lance_mod.settings.EMBEDDINGS_DIMENSION
    dummy_query = [0.15] * lance_mod.settings.EMBEDDINGS_DIMENSION

    with patch.object(lance_mod, "db", temp_db), \
         patch.object(lance_mod, "TABLE_NAME", table_name), \
         patch.object(lance_mod.embeddings, "embed_documents", return_value=[dummy_vec_a, dummy_vec_b]), \
         patch.object(lance_mod.embeddings, "embed_query", return_value=dummy_query):

        # 1. Initialize empty table with full schema
        lance_mod.initialize_collection()

        # 2. User A ingests a secret document
        doc_a = Document(
            page_content="Secret document belonging to user A (10000@qq.com)",
            metadata={
                "source": "http://secret.a",
                "page": "1",
                "filename": "note_a.md",
                "belongs_to": "10000@qq.com",
                "user_id": "1",
                "file_id": "101",
                "resource_id": "101",
                "source_type": "note"
            }
        )

        # User B ingests a public document
        doc_b = Document(
            page_content="Public document belonging to user B (other@test.com)",
            metadata={
                "source": "http://public.b",
                "page": "1",
                "filename": "note_b.md",
                "belongs_to": "other@test.com",
                "user_id": "2",
                "file_id": "202",
                "resource_id": "202",
                "source_type": "note"
            }
        )

        lance_mod.add_documents([doc_a, doc_b])

        # 3. User B searches vector store -> MUST NOT return A's chunk
        results_b = lance_mod.fetch_documents(
            include_selected=None,
            exclude_selected=None,
            window_size=10,
            username="other@test.com",
            prompt="document",
            source_type="note",
            user_id=2
        )

        assert len(results_b) == 1
        assert results_b[0][0].page_content == "Public document belonging to user B (other@test.com)"
        assert str(results_b[0][0].metadata["user_id"]) == "2"

        # 4. User A searches vector store -> MUST NOT return B's chunk
        results_a = lance_mod.fetch_documents(
            include_selected=None,
            exclude_selected=None,
            window_size=10,
            username="10000@qq.com",
            prompt="document",
            source_type="note",
            user_id=1
        )

        assert len(results_a) == 1
        assert results_a[0][0].page_content == "Secret document belonging to user A (10000@qq.com)"
        assert str(results_a[0][0].metadata["user_id"]) == "1"


def test_fetch_documents_by_resource_isolation(tmp_path):
    """Test resource-level vector fetch isolation."""
    temp_db = lancedb.connect(str(tmp_path / "lancedb_test_iso_res"))
    table_name = "test_vectors_iso_res"

    dummy_vec = [0.1] * lance_mod.settings.EMBEDDINGS_DIMENSION

    with patch.object(lance_mod, "db", temp_db), \
         patch.object(lance_mod, "TABLE_NAME", table_name), \
         patch.object(lance_mod.embeddings, "embed_documents", return_value=[dummy_vec]):

        lance_mod.initialize_collection()

        doc_a = Document(
            page_content="Resource 500 chunk for user 1",
            metadata={
                "source": "http://res.500",
                "page": "1",
                "filename": "res.md",
                "belongs_to": "10000@qq.com",
                "user_id": "1",
                "file_id": "500",
                "resource_id": "500",
                "source_type": "file"
            }
        )
        lance_mod.add_documents([doc_a])

        # When User B tries to fetch resource 500 by ID, it must return 0 results due to user_id filter
        res_b = lance_mod.fetch_documents_by_resource(
            resource_id=500,
            source_type="file",
            user_id=2,
            username="other@test.com"
        )
        assert len(res_b) == 0

        # When User A fetches resource 500, it returns the chunk
        res_a = lance_mod.fetch_documents_by_resource(
            resource_id=500,
            source_type="file",
            user_id=1,
            username="10000@qq.com"
        )
        assert len(res_a) == 1
        assert res_a[0][0].page_content == "Resource 500 chunk for user 1"


def test_user_id_prefix_collision_isolation(tmp_path):
    """Test that user_id=1 does NOT leak documents belonging to user_id=10."""
    temp_db = lancedb.connect(str(tmp_path / "lancedb_test_iso_prefix"))
    table_name = "test_vectors_prefix"

    vec_1 = [0.1] * lance_mod.settings.EMBEDDINGS_DIMENSION
    vec_10 = [0.2] * lance_mod.settings.EMBEDDINGS_DIMENSION
    query_vec = [0.15] * lance_mod.settings.EMBEDDINGS_DIMENSION

    with patch.object(lance_mod, "db", temp_db), \
         patch.object(lance_mod, "TABLE_NAME", table_name), \
         patch.object(lance_mod.embeddings, "embed_documents", return_value=[vec_1, vec_10]), \
         patch.object(lance_mod.embeddings, "embed_query", return_value=query_vec):

        lance_mod.initialize_collection()

        doc_u1 = Document(
            page_content="User 1 private chunk",
            metadata={
                "source": "http://u1.txt",
                "page": "1",
                "filename": "u1.txt",
                "belongs_to": "u1@test.com",
                "user_id": "1",
                "file_id": "1",
                "resource_id": "1",
                "source_type": "file"
            }
        )
        doc_u10 = Document(
            page_content="User 10 private chunk",
            metadata={
                "source": "http://u10.txt",
                "page": "1",
                "filename": "u10.txt",
                "belongs_to": "u10@test.com",
                "user_id": "10",
                "file_id": "10",
                "resource_id": "10",
                "source_type": "file"
            }
        )
        lance_mod.add_documents([doc_u1, doc_u10])

        # Query as user 1 -> MUST NOT return user 10's chunk
        results_1 = lance_mod.fetch_documents(
            include_selected=None,
            exclude_selected=None,
            window_size=10,
            username="u1@test.com",
            prompt="chunk",
            user_id=1
        )
        assert len(results_1) == 1
        assert results_1[0][0].page_content == "User 1 private chunk"
        assert str(results_1[0][0].metadata["user_id"]) == "1"

        # Query as user 10 -> MUST NOT return user 1's chunk
        results_10 = lance_mod.fetch_documents(
            include_selected=None,
            exclude_selected=None,
            window_size=10,
            username="u10@test.com",
            prompt="chunk",
            user_id=10
        )
        assert len(results_10) == 1
        assert results_10[0][0].page_content == "User 10 private chunk"
        assert str(results_10[0][0].metadata["user_id"]) == "10"


def test_resource_id_prefix_collision_isolation(tmp_path):
    """Test that resource_id=1 does NOT match resource_id=10."""
    temp_db = lancedb.connect(str(tmp_path / "lancedb_test_res_prefix"))
    table_name = "test_vectors_res_prefix"

    vec = [0.1] * lance_mod.settings.EMBEDDINGS_DIMENSION

    with patch.object(lance_mod, "db", temp_db), \
         patch.object(lance_mod, "TABLE_NAME", table_name), \
         patch.object(lance_mod.embeddings, "embed_documents", return_value=[vec, vec]):

        lance_mod.initialize_collection()

        doc_r1 = Document(
            page_content="Resource 1 content",
            metadata={
                "source": "http://res1.txt",
                "page": "1",
                "filename": "res1.txt",
                "belongs_to": "user@test.com",
                "user_id": "1",
                "resource_id": "1",
                "file_id": "1",
                "source_type": "file"
            }
        )
        doc_r10 = Document(
            page_content="Resource 10 content",
            metadata={
                "source": "http://res10.txt",
                "page": "1",
                "filename": "res10.txt",
                "belongs_to": "user@test.com",
                "user_id": "1",
                "resource_id": "10",
                "file_id": "10",
                "source_type": "file"
            }
        )
        lance_mod.add_documents([doc_r1, doc_r10])

        res_1 = lance_mod.fetch_documents_by_resource(resource_id=1, source_type="file", user_id=1)
        assert len(res_1) == 1
        assert res_1[0][0].page_content == "Resource 1 content"

        res_10 = lance_mod.fetch_documents_by_resource(resource_id=10, source_type="file", user_id=1)
        assert len(res_10) == 1
        assert res_10[0][0].page_content == "Resource 10 content"


def test_fts5_chinese_2char_and_batch_isolation():
    """Test FTS5 batch insert and 2-character Chinese keyword search with user isolation."""
    import sqlite3
    from backend.core.fts5_utils import create_fts5_table, insert_fts5_batch, match_fts5

    conn = sqlite3.connect(":memory:")
    create_fts5_table(conn)

    rows = [
        {
            "chunk_id": "c_u1_1",
            "title": "闭包详解",
            "filename": "closure.md",
            "page_content": "Python中的闭包与作用域分析",
            "user_id": "1",
            "belongs_to": "u1@test.com",
            "source_type": "note"
        },
        {
            "chunk_id": "c_u2_1",
            "title": "闭包其他",
            "filename": "closure2.md",
            "page_content": "另一个用户的闭包笔记",
            "user_id": "2",
            "belongs_to": "u2@test.com",
            "source_type": "note"
        }
    ]
    insert_fts5_batch(conn, rows)

    # 2-character Chinese search for user 1
    u1_matches = match_fts5(conn, "闭包", user_id=1)
    assert len(u1_matches) == 1
    assert u1_matches[0]["chunk_id"] == "c_u1_1"
    assert u1_matches[0]["title"] == "闭包详解"

    # User 2 isolation check
    u2_matches = match_fts5(conn, "闭包", user_id=2)
    assert len(u2_matches) == 1
    assert u2_matches[0]["chunk_id"] == "c_u2_1"

    # User 3 isolation check (must return 0)
    u3_matches = match_fts5(conn, "闭包", user_id=3)
    assert len(u3_matches) == 0
