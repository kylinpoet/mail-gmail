from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ProxyBase(BaseModel):
    name: str = "Proxy"
    type: str = Field("http", pattern="^(http|socks5)$")
    host: str
    port: int = Field(..., ge=1, le=65535)
    username: Optional[str] = None
    enabled: bool = True
    is_global: bool = False
    timeout_seconds: int = Field(20, ge=1, le=120)
    region: Optional[str] = None
    remark: Optional[str] = None


class ProxyCreate(ProxyBase):
    password: Optional[str] = None


class ProxyUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(http|socks5)$")
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: Optional[bool] = None
    is_global: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(None, ge=1, le=120)
    region: Optional[str] = None
    remark: Optional[str] = None


class ProxyRead(ProxyBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    password_configured: bool
    last_test_ok: Optional[bool] = None
    last_test_at: Optional[datetime] = None
    last_test_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ProxyTestResponse(BaseModel):
    ok: bool
    error: Optional[str] = None
    elapsed_ms: int


class ProxyImapTestResponse(ProxyTestResponse):
    target: str
    stage: str
    detail: Optional[str] = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    auth_type: str
    google_subject: Optional[str] = None
    scope: str
    status: str
    proxy_mode: str = "auto"
    proxy_id: Optional[int] = None
    sync_enabled: bool
    sync_interval_seconds: int
    initial_sync_days: int
    initial_sync_limit: int
    last_history_id: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None
    remark: Optional[str] = None
    app_password_configured: bool
    created_at: datetime
    updated_at: datetime


class AccountCreate(BaseModel):
    email: EmailStr
    app_password: str = Field(..., min_length=8, max_length=128)
    proxy_mode: str = Field("auto", pattern="^(auto|direct|fixed)$")
    proxy_id: Optional[int] = None
    sync_enabled: bool = True
    sync_interval_seconds: int = Field(300, ge=60, le=86400)
    initial_sync_days: int = Field(30, ge=1, le=3650)
    initial_sync_limit: int = Field(1, ge=1, le=5000)
    remark: Optional[str] = None


class AccountUpdate(BaseModel):
    proxy_mode: Optional[str] = Field(None, pattern="^(auto|direct|fixed)$")
    proxy_id: Optional[int] = None
    app_password: Optional[str] = Field(None, min_length=8, max_length=128)
    sync_enabled: Optional[bool] = None
    sync_interval_seconds: Optional[int] = Field(None, ge=60, le=86400)
    initial_sync_days: Optional[int] = Field(None, ge=1, le=3650)
    initial_sync_limit: Optional[int] = Field(None, ge=1, le=5000)
    status: Optional[str] = Field(None, pattern="^(active|auth_failed|proxy_failed|rate_limited|disabled)$")
    remark: Optional[str] = None


class AccountTestResponse(BaseModel):
    ok: bool
    email: Optional[str] = None
    error: Optional[str] = None


class AliasGenerateRequest(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=120)
    count: int = Field(..., ge=0, le=10000)
    label: Optional[str] = Field(None, max_length=120)


class AliasBatchRequest(BaseModel):
    ids: List[int] = Field(..., min_length=1)


class AliasBatchUpdateRequest(AliasBatchRequest):
    enabled: bool


class AliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    alias_address: EmailStr
    pattern: str
    sequence: int
    label: Optional[str] = None
    enabled: bool
    message_count: int
    last_seen_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    account_ids: Optional[List[int]] = None
    aliases: Optional[List[EmailStr]] = None
    ip_allowlist: Optional[List[str]] = None
    rate_limit_per_minute: int = Field(60, ge=1, le=10000)


class ApiKeyRead(BaseModel):
    id: int
    name: str
    active: bool
    account_ids: Optional[List[int]] = None
    aliases: Optional[List[str]] = None
    ip_allowlist: Optional[List[str]] = None
    rate_limit_per_minute: int
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ApiKeyCreated(ApiKeyRead):
    api_key: str


class SyncJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    status: str
    requested_by: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    fetched_count: int
    inserted_count: int
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SyncRequest(BaseModel):
    limit: Optional[int] = Field(1, ge=1, le=5000)


class MessageBatchRequest(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=1000)


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gmail_attachment_id: str
    part_id: Optional[str] = None
    filename: str
    mime_type: Optional[str] = None
    size: Optional[int] = None
    cached_path: Optional[str] = None


class MessageListItem(BaseModel):
    id: int
    account_id: int
    alias_id: Optional[int] = None
    alias_address: Optional[str] = None
    gmail_message_id: str
    thread_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    recipients: List[str] = []
    received_at: Optional[datetime] = None
    snippet: Optional[str] = None
    has_attachment: bool


class MessageDetail(MessageListItem):
    cc: List[str] = []
    rfc_message_id: Optional[str] = None
    history_id: Optional[str] = None
    text_body: Optional[str] = None
    html_body: Optional[str] = None
    raw_headers: Dict[str, Any] = {}
    attachments: List[AttachmentRead] = []


class MessagePage(BaseModel):
    items: List[MessageListItem]
    next_cursor: Optional[int] = None


class AttachmentPayload(BaseModel):
    filename: str
    mime_type: Optional[str] = None
    size: Optional[int] = None
    data_base64url: str
