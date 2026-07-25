import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.api.models import Base, Note, FileUpload, Link
from backend.api.services.structured_recall import search_resources

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    with Session(engine) as session:
        # User 1 resources
        session.add(Note(id=1, title="Test Note 1", url="http://note1", user_id=1))
        session.add(Note(id=2, title="Other Document", url="http://note2", user_id=1))
        session.add(FileUpload(id=1, original_filename="test_file.pdf", file_url="http://file1", user_id=1))
        session.add(Link(id=1, title="Test Link", url="http://link1", user_id=1))
        session.add(Link(id=2, title="Random", url="http://test.com", user_id=1))
        
        # User 2 resources
        session.add(Note(id=3, title="Test Note 2", url="http://note3", user_id=2))
        session.commit()
    
    return engine

def test_search_resources_empty(test_db):
    assert search_resources("", 1) == []
    assert search_resources("   ", 1) == []
    assert search_resources(None, 1) == []
    assert search_resources("test", None) == []

def test_search_resources_no_match(test_db):
    from unittest.mock import patch
    with patch('backend.api.services.structured_recall.sync_engine', test_db):
        results = search_resources("notfound", 1)
        assert results == []

def test_search_resources_user_isolation(test_db):
    from unittest.mock import patch
    with patch('backend.api.services.structured_recall.sync_engine', test_db):
        # User 1 searching for 'test'
        results = search_resources("test", 1)
        
        # Should find Note 1, FileUpload 1, Link 1, Link 2 (because url contains test)
        assert len(results) == 4
        source_types = [r["source_type"] for r in results]
        assert source_types.count("note") == 1
        assert source_types.count("file") == 1
        assert source_types.count("link") == 2
        
        # Ensure Note 3 (belonging to User 2) is NOT included
        assert 3 not in [r["resource_id"] for r in results if r["source_type"] == "note"]

def test_search_resources_limit(test_db):
    from unittest.mock import patch
    with patch('backend.api.services.structured_recall.sync_engine', test_db):
        results = search_resources("test", 1, limit=2)
        assert len(results) == 2
