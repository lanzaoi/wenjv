import pytest
from unittest.mock import patch, MagicMock
from backend.vector_store.lance_db import fetch_documents_by_resource
from langchain.schema import Document

def test_fetch_by_resource_with_resource_id():
    # Test when schema has resource_id
    with patch('backend.vector_store.lance_db.db.open_table') as m_open:
        m_table = MagicMock()
        m_open.return_value = m_table
        
        # Mock schema names
        m_table.schema.names = ["resource_id", "user_id", "source_type", "page_content"]
        
        # Mock search results
        import pandas as pd
        m_df = pd.DataFrame([{
            "resource_id": "1",
            "user_id": "1",
            "source_type": "file",
            "page_content": "chunk 1",
            "vector": [0.1, 0.2]
        }])
        
        m_table.search.return_value.where.return_value.limit.return_value.to_pandas.return_value = m_df
        
        results = fetch_documents_by_resource(1, "file", user_id=1, username="test@test.com")
        
        assert len(results) == 1
        assert results[0][0].page_content == "chunk 1"
        assert results[0][0].metadata["resource_id"] == "1"
        
        # Verify correct where clause
        where_expr = m_table.search.return_value.where.call_args[0][0]
        assert "(user_id LIKE '%1%' OR belongs_to = 'test@test.com')" in where_expr
        assert "(resource_id LIKE '%1%')" in where_expr

def test_fetch_by_resource_fallback_file_id():
    # Test when schema has NO resource_id but has file_id
    with patch('backend.vector_store.lance_db.db.open_table') as m_open:
        m_table = MagicMock()
        m_open.return_value = m_table
        
        m_table.schema.names = ["file_id", "user_id", "source_type", "page_content"]
        
        import pandas as pd
        m_df = pd.DataFrame([{
            "file_id": "1",
            "user_id": "1",
            "source_type": "file",
            "page_content": "chunk old",
            "vector": [0.1, 0.2]
        }])
        
        m_table.search.return_value.where.return_value.limit.return_value.to_pandas.return_value = m_df
        
        results = fetch_documents_by_resource(1, "file", user_id=1)
        
        assert len(results) == 1
        assert results[0][0].page_content == "chunk old"
        assert "resource_id" not in results[0][0].metadata
        assert results[0][0].metadata["file_id"] == "1"
        
        where_expr = m_table.search.return_value.where.call_args[0][0]
        assert "file_id LIKE '%1%'" in where_expr
        assert "resource_id" not in where_expr
