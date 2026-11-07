# backend/database.py
import os
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import create_engine, Column, String, Text, Integer, LargeBinary, DateTime, Float, Boolean, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.sql import func

from backend.config import settings

# Create base model
class Base(DeclarativeBase):
    pass

class EmbedCacheTable(Base):
    __tablename__ = "embed_cache"

    text_hash = Column(String, primary_key=True, nullable=False)
    model = Column(String, primary_key=True, nullable=False)
    vector = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

class QueryResultCacheTable(Base):
    __tablename__ = "query_result_cache"

    query_hash = Column(String, primary_key=True, nullable=False)
    user_id = Column(Integer, primary_key=True, nullable=False)
    result_json = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)

class QueryLogsTable(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
    latency_ms = Column(Float, nullable=False, default=0.0)
    v_hits = Column(Integer, nullable=False, default=0)
    fts5_hits = Column(Integer, nullable=False, default=0)
    s_hits = Column(Integer, nullable=False, default=0)
    total_hits = Column(Integer, nullable=False, default=0)
    cache_hit = Column(Boolean, nullable=False, default=False)
    error = Column(Text, nullable=True)

class ApiCallCountsTable(Base):
    __tablename__ = "api_call_counts"

    provider = Column(String, primary_key=True, nullable=False)
    call_type = Column(String, primary_key=True, nullable=False)
    call_count = Column(Integer, nullable=False, default=0)
    last_reset = Column(DateTime, nullable=True)

class ChunkMappingTable(Base):
    __tablename__ = "chunk_mapping"

    chunk_id = Column(String, primary_key=True, nullable=False)
    chunk_group = Column(String, nullable=False, index=True)
    chunk_order = Column(Integer, nullable=False)
    resource_id = Column(String, nullable=True, index=True)

class DocEmbeddingTable(Base):
    __tablename__ = "doc_embeddings"

    resource_id = Column(String, primary_key=True, nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    dims = Column(Integer, nullable=False, default=1024)
    chunk_count = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow)

@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Enable WAL mode, NORMAL synchronous, and busy timeout for concurrent SQLite throughput."""
    if hasattr(dbapi_connection, "cursor"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
        except Exception:
            pass
        finally:
            cursor.close()

# Create synchronous engine for initial setup
sync_engine = create_engine(
    settings.DATABASE_URL.replace("+aiosqlite", ""),
    connect_args={"check_same_thread": False}
)

_cache_engine = None

def get_cache_engine():
    global _cache_engine
    if _cache_engine is None:
        db_path = getattr(settings, "CACHE_DIR", os.path.join(settings.BASE_DIR, "cache.db"))
        _cache_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    return _cache_engine

# Create async engine for FastAPI
engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)
async_session_maker = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False)

# Create tables


def _ensure_sqlite_columns(connection):
    """
    Lightweight additive migrations for existing SQLite DBs.
    create_all() does not add new columns to already-created tables.
    """
    upgrades = {
        "file_uploads": [("error_message", "TEXT"), ("tags", "TEXT DEFAULT '[]'")],
        "notes": [("error_message", "TEXT"), ("tags", "TEXT DEFAULT '[]'")],
        "links": [("error_message", "TEXT"), ("tags", "TEXT DEFAULT '[]'")],
    }
    for table, columns in upgrades.items():
        existing = {
            row[1]
            for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        }
        if not existing:
            continue
        for col_name, col_type in columns:
            if col_name not in existing:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"
                )


from backend.core.fts5_utils import create_fts5_table

def create_db_and_tables():
    Base.metadata.create_all(sync_engine)
    with sync_engine.begin() as conn:
        # Only SQLite needs this simple path; other DBs should use real migrations later.
        if sync_engine.dialect.name == "sqlite":
            _ensure_sqlite_columns(conn)
    
    if sync_engine.dialect.name == "sqlite":
        raw_conn = sync_engine.raw_connection()
        try:
            create_fts5_table(raw_conn)
        finally:
            raw_conn.close()

# Get async session


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
