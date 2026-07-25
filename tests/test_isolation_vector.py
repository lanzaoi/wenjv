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
