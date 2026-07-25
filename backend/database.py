# backend/database.py
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from backend.config import settings

# Create base model
Base = declarative_base()

# Create synchronous engine for initial setup
sync_engine = create_engine(
    settings.DATABASE_URL.replace("+aiosqlite", ""),
    connect_args={"check_same_thread": False}
)

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
        "file_uploads": [("error_message", "TEXT")],
        "notes": [("error_message", "TEXT")],
        "links": [("error_message", "TEXT")],
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
