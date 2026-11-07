# backend/api/schemas.py
import json
from typing import Optional, List, Dict
from fastapi_users import schemas
from datetime import datetime
from pydantic import HttpUrl, Field, ConfigDict, field_validator
from backend.config import settings


def _parse_tags_value(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


class UserRead(schemas.BaseUser[int]):
    username: Optional[str] = None


class UserCreate(schemas.BaseUserCreate):
    username: Optional[str] = None


class UserUpdate(schemas.BaseUserUpdate):
    username: Optional[str] = None


class TokenPayload(schemas.BaseModel):
    token: str


class FileUploadResponse(schemas.BaseModel):
    id: Optional[int] = None
    filename: str
    file_url: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v):
        return _parse_tags_value(v)

    model_config = ConfigDict(from_attributes=True)


class FileUploadDB(schemas.BaseModel):
    id: int
    filename: str
    original_filename: str
    file_path: str
    file_url: str
    content_type: str
    created_at: datetime
    user_id: int

    model_config = ConfigDict(from_attributes=True)


class LinkBase(schemas.BaseModel):
    url: HttpUrl
    headers: Optional[Dict[str, str]] = Field(
        default=settings.DEFAULT_HEADERS, description="Custom request headers")


class LinkCreate(LinkBase):
    tags: Optional[List[str]] = None


class LinkCrawl(LinkBase):
    pass


class LinkResponse(LinkBase):
    id: int
    title: Optional[str] = None
    favicon: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v):
        return _parse_tags_value(v)

    model_config = ConfigDict(from_attributes=True)


class LinkCrawlResponse(LinkBase):
    status: str

    model_config = ConfigDict(from_attributes=True)


class BulkLinkCreate(schemas.BaseModel):
    urls: List[HttpUrl]
    headers: Optional[Dict[str, str]] = Field(
        default=settings.DEFAULT_HEADERS, description="Custom request headers to use for all URLs")


class BulkLinkResponse(schemas.BaseModel):
    links_added: int

    model_config = ConfigDict(from_attributes=True)


class DocumentSearchRequest(schemas.BaseModel):
    prompt: str
    include_sources: Optional[List[str]] = None
    exclude_sources: Optional[List[str]] = None
    window_size: Optional[int] = 5
    source_type: Optional[str] = None
    tags: Optional[List[str]] = None


class DocumentMetadata(schemas.BaseModel):
    source: Optional[str] = None
    page: Optional[str] = None
    source_type: Optional[str] = None
    belongs_to: Optional[str] = None
    id: Optional[str] = None
    title: Optional[str] = None
    link_id: Optional[str] = None
    file_id: Optional[str] = None
    filename: Optional[str] = None
    user_id: Optional[str] = None
    tag_matched: Optional[bool] = None
    tag_fallback: Optional[bool] = None
    matched_tags_count: Optional[int] = None
    image_path: Optional[str] = None
    image_url: Optional[str] = None
    has_image: Optional[bool] = None

    model_config = ConfigDict(extra="ignore")


class DocumentResult(schemas.BaseModel):
    page_content: str
    metadata: DocumentMetadata
    score: float


class DocumentSearchResponse(schemas.BaseModel):
    documents: List[DocumentResult]
    count: int


class NoteCreateRequest(schemas.BaseModel):
    content: str
    title: str
    tags: Optional[List[str]] = None


class NoteUpdateRequest(schemas.BaseModel):
    content: str


class NoteUpdateResponse(schemas.BaseModel):
    filename: str
    updated: bool


class NoteBulkSyncResponse(schemas.BaseModel):
    count: int
    updated: bool


class NoteCreateResponse(schemas.BaseModel):
    id: int
    url: str
    title: str
    status: str


class NoteResponse(schemas.BaseModel):
    id: int
    url: str
    title: str
    filename: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v):
        return _parse_tags_value(v)

    model_config = ConfigDict(from_attributes=True)


class TagUpdateRequest(schemas.BaseModel):
    tags: List[str]


class TagSummaryItem(schemas.BaseModel):
    name: str
    count: int


class TagSummaryResponse(schemas.BaseModel):
    tags: List[TagSummaryItem]


class TagBackfillResponse(schemas.BaseModel):
    enqueued_count: int


class NoteList(schemas.BaseModel):
    notes: List[NoteResponse]
    total: int


class LinksList(schemas.BaseModel):
    links: List[LinkResponse]
    total: int


class FilesList(schemas.BaseModel):
    files: List[FileUploadResponse]
    total: int


class FilePollingResponse(schemas.BaseModel):
    status: str
    error_message: Optional[str] = None


class ResourceDeletedResponse(schemas.BaseModel):
    status: str


class JobResponse(schemas.BaseModel):
    id: int
    job_type: str
    resource_id: int
    status: str
    attempts: int
    max_attempts: int
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
