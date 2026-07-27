# backend/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator, field_validator
from pathlib import Path
from typing import Dict
from backend.vector_store.models import StoreEngine
import os
import json


def get_env_file_path():
    """Get the path to the .env file in the base directory"""
    home_dir = os.path.expanduser("~")
    base_dir = os.path.join(home_dir, ".config", "inquisitive")

    Path(base_dir).mkdir(parents=True, exist_ok=True)

    env_file_path = os.path.join(base_dir, "backend.env")

    if not os.path.exists(env_file_path):
        with open(env_file_path, 'w') as f:
            f.write("# Backend environment variables for personal knowledge base\n")

    return env_file_path


# It is possible to override all the defaults values
# by specifying env variables or adding variables in backend.env.
# However, if we decide to override default directory locations
# then we need to make sure that one needs to create
# all the relevant directories and sub-directories manually.
# Data layout under BASE_DIR (default: ~/.config/inquisitive):
#   uploads/  logs/  inquisitive.db  lance_db/
class Settings(BaseSettings):
    # BASIC SERVER SETTINGS
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000
    SERVER_LOG_LEVEL: str = "debug"

    OLLAMA_HOST: str = "http://0.0.0.0:11434"

    # BASIC DIRECTORY CREATION
    HOME_DIR: str = os.path.expanduser("~")
    CONFIG_DIR: str = os.path.join(HOME_DIR, ".config")
    CONFIG_DIR_PATH: Path = Path(CONFIG_DIR)
    CONFIG_DIR_PATH.mkdir(exist_ok=True)

    BASE_DIR: str = os.path.join(CONFIG_DIR, "inquisitive")
    BASE_DIR_PATH: Path = Path(BASE_DIR)
    BASE_DIR_PATH.mkdir(exist_ok=True)

    UPLOAD_DIR: str = os.path.join(BASE_DIR, "uploads")
    UPLOAD_DIR_PATH: Path = Path(UPLOAD_DIR)
    UPLOAD_DIR_PATH.mkdir(exist_ok=True)

    LOGS_DIR: str = os.path.join(BASE_DIR, "logs")
    LOGS_DIR_PATH: Path = Path(LOGS_DIR)
    LOGS_DIR_PATH.mkdir(exist_ok=True)

    LOG_FILE_NAME: str = os.path.join(LOGS_DIR, "backend.log")

    # Keep local machines usable; override via backend.env if needed
    LINKS_JOB_QUEUE_CONCURRENCY: int = 8
    FILES_JOB_QUEUE_CONCURRENCY: int = 4

    # Durable job runner
    JOB_WORKER_CONCURRENCY: int = 6
    JOB_MAX_ATTEMPTS: int = 3
    JOB_POLL_INTERVAL_SECONDS: float = 2.0
    # Re-queue jobs stuck in "running" longer than this (seconds)
    JOB_STALE_SECONDS: int = 30 * 60

    # Upload safety (backend enforcement; FE whitelist should stay in sync)
    ALLOWED_UPLOAD_EXTENSIONS: list[str] = [
        "txt", "pdf", "md", "json", "sh", "markdown",
        "docx", "pptx", "csv",
    ]
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024  # 25 MiB

    @model_validator(mode="after")
    def extend_upload_extensions(self) -> "Settings":
        if self.OCR_MODE != "off":
            for ext in ["png", "jpg", "jpeg"]:
                if ext not in self.ALLOWED_UPLOAD_EXTENSIONS:
                    self.ALLOWED_UPLOAD_EXTENSIONS.append(ext)
        return self

    # Sqlite Path
    SQLITE_DB_PATH: str = os.path.join(BASE_DIR, "inquisitive.db")

    # Vector store path
    CHROMA_VECTOR_STORE_PERSISTS_DIRECTORY: str = os.path.join(
        BASE_DIR, "chroma_db")
    MILVUS_VECTOR_STORE_URL: str = os.path.join(BASE_DIR, "milvus_data.db")
    LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY: str = os.path.join(
        BASE_DIR, "lance_db")

    # Default vector database
    DEFAULT_VECTOR_DB: str = StoreEngine.LANCE

    VECTOR_STORE_COLLECTION_NAME: str = "document_store"

    # Modify and use different embedding model if needed
    # Use "chroma/all-minilm-l6-v2-f32" & 384 for local-only deployment
    EMBEDDINGS_MODEL: str = "BAAI/bge-m3"
    EMBEDDINGS_DIMENSION: int = 1024
    
    # Dual Provider Settings (B0)
    EMBEDDING_PROVIDER: str = "ollama"
    CHAT_PROVIDER: str = "ollama"
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""
    CHAT_API_BASE: str = ""
    CHAT_API_KEY: str = ""
    CHAT_MODEL: str = ""

    # RAG Refusal settings
    RAG_REFUSE_ON_EMPTY: bool = True
    
    # Hybrid Search Settings (Y2+)
    HYBRID_SEARCH_ENABLED: bool = False
    HYBRID_KEYWORD_BACKEND: str = "fts5"  # fts5 | like
    HYBRID_VECTOR_MAX_DISTANCE: float = 0.8
    HYBRID_RRF_K: int = 5
    HYBRID_RRF_WEIGHT_VECTOR: float = 1.0
    HYBRID_RRF_WEIGHT_KEYWORD: float = 1.0

    # ---- 1.2 RAG Depth ----

    # Rerank (cross-encoder)
    RERANK_ENABLED: bool = False
    RERANK_PROVIDER: str = "siliconflow"
    RERANK_API_BASE: str = ""
    RERANK_API_KEY: str = ""
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANK_CANDIDATES: int = 20
    RERANK_TIMEOUT_SECONDS: int = 8

    # MMR
    MMR_ENABLED: bool = True
    MMR_LAMBDA: float = 0.7
    MMR_MODE: str = "standard"  # "standard" | "same_resource"

    # Structured Recall
    STRUCTURED_RECALL_ENABLED: bool = True
    HYBRID_RRF_WEIGHT_STRUCTURED: float = 1.0
    STRUCTURED_RECALL_LIMIT: int = 20

    # Caching Layer (1.4)
    EMBEDDING_CACHE_ENABLED: bool = True
    QUERY_CACHE_ENABLED: bool = True
    QUERY_CACHE_TTL_SECONDS: int = 300
    CACHE_DIR: str = os.path.join(BASE_DIR, "cache.db")

    # Observability Layer (1.4)
    ADMIN_ENABLED: bool = True
    OBS_ALERT_FTS5_ZERO_HIT_THRESHOLD: int = 10
    OBS_ALERT_FTS5_ZERO_HIT_STREAK: int = 10
    OBS_ALERT_LATENCY_STREAK: int = 5
    OBS_ALERT_LATENCY_THRESHOLD_MS: float = 5000.0
    OBS_ALERT_ERROR_STREAK_THRESHOLD: int = 5
    OBS_ALERT_ERROR_STREAK: int = 5
    OBS_ALERT_COOLDOWN_SECONDS: int = 300
    OBS_LOG_RETENTION_DAYS: int = 30

    # Query Understanding Layer (1.4)
    QUERY_CLASSIFIER_ENABLED: bool = False
    QUERY_CLASSIFIER_SHORT_BOOST: float = 2.0
    QUERY_CLASSIFIER_SHORT_KEYWORD_BOOST: float = 2.0
    QUERY_CLASSIFIER_LONG_BOOST: float = 2.0
    QUERY_CLASSIFIER_LONG_QUESTION_BOOST: float = 2.0
    QUERY_CLASSIFIER_MAX_WEIGHT: float = 5.0

    # OCR (AI Studio v2 async)
    OCR_MODE: str = "off"
    OCR_PROVIDER: str = "aistudio"
    OCR_AISTUDIO_ACCESS_TOKEN: str = ""
    OCR_API_BASE: str = "https://paddleocr.aistudio-app.com/api/v2/ocr"
    OCR_MODEL: str = "PaddleOCR-VL-1.6"
    OCR_MIN_CHARS: int = 40
    OCR_MAX_PAGES: int = 30
    OCR_TIMEOUT_SECONDS: int = 120

    TEXT_SPLITTER_CHUNK_SIZE:  int = 1500
    TEXT_SPLITTER_CHUNK_OVERLAP:  int = 150
    TEXT_SPLITTER_SEPARATORS: list[str] = ["\n\n", "\n", "。", "，", " ", ""]

    # ---- 1.5 Chunking 2.0 ----

    # Small-to-large: retrieve with small chunks, expand context to neighbors
    CHUNK_EXPAND_ENABLED: bool = False
    CHUNK_EXPAND_WINDOW: int = 2
    CHUNK_RETRIEVAL_SIZE: int = 256

    # Multimodal (1.5)
    MULTIMODAL_ENABLED: bool = False
    GEMINI_API_KEY: str = os.environ.get("GOOGLE_API_KEY", "")
    GEMINI_VL_MODEL: str = "gemini-2.0-flash"

    # Late Chunking (1.5)
    LATE_CHUNKING_ENABLED: bool = False
    LATE_CHUNKING_TOP_DOCS: int = 5

    # Modify if needed to use other relational DB
    DATABASE_URL: str = f"sqlite+aiosqlite:///{SQLITE_DB_PATH}"

    # JWT settings
    # In production, use a secure key
    SECRET_KEY: str = "YOUR_SECRET_KEY_CHANGE_THIS"
    RESET_PASSWORD_TOKEN_SECRET: str = "YOUR_SECRET_KEY_CHANGE_THIS"
    VERIFICATION_TOKEN_SECRET: str = "YOUR_SECRET_KEY_CHANGE_THIS"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24  # 1 day (override in backend.env if needed)
    JWT_TOKEN_AUDIENCE: str = "fastapi-users:auth"

    # CORS settings
    # Streamlit UI default port
    CORS_ORIGINS: list[str] = ["http://localhost:8501"]
    WINDOW_SIZE_MULTIPLIER: int = 10
    DEFAULT_HEADERS: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    LOGGER_NAME: str = "knowledge_base_backend"
    LOG_FORMAT: str = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=get_env_file_path(),
        env_file_encoding='utf-8',
    )

    @field_validator("DEFAULT_HEADERS", mode="before")
    @classmethod
    def parse_headers(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [item.strip() for item in v.split(',')]
        return v

    @field_validator("ALLOWED_UPLOAD_EXTENSIONS", mode="before")
    @classmethod
    def parse_extensions(cls, v):
        """保留 .lstrip('.') 行为：用户可在 env 里写 .pdf, .md"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [item.strip().lstrip('.') for item in v.split(',') if item.strip()]
        return v


settings = Settings()


def is_insecure_default_secret() -> bool:
    insecure = {
        "YOUR_SECRET_KEY_CHANGE_THIS",
        "change-me",
        "secret",
    }
    return (
        settings.SECRET_KEY in insecure
        or settings.RESET_PASSWORD_TOKEN_SECRET in insecure
        or settings.VERIFICATION_TOKEN_SECRET in insecure
    )
