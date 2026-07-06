from datetime import UTC, datetime

from app.core.platform_patch import patch_windows_platform_machine

patch_windows_platform_machine()

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin(object):
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ProxyConfig(TimestampMixin, Base):
    __tablename__ = "proxy_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, default="Proxy")
    type = Column(String(20), nullable=False, default="http")
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String(255), nullable=True)
    encrypted_password = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    is_global = Column(Boolean, nullable=False, default=False)
    timeout_seconds = Column(Integer, nullable=False, default=20)
    region = Column(String(80), nullable=True)
    remark = Column(Text, nullable=True)
    last_test_ok = Column(Boolean, nullable=True)
    last_test_at = Column(DateTime, nullable=True)
    last_test_error = Column(Text, nullable=True)

    accounts = relationship("GmailAccount", back_populates="proxy")


class GmailAccount(TimestampMixin, Base):
    __tablename__ = "gmail_accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    auth_type = Column(String(40), nullable=False, default="app_password")
    google_subject = Column(String(255), unique=True, nullable=True, index=True)
    encrypted_app_password = Column(Text, nullable=True)
    encrypted_refresh_token = Column(Text, nullable=True)
    scope = Column(Text, nullable=False, default="https://www.googleapis.com/auth/gmail.readonly")
    status = Column(String(40), nullable=False, default="oauth_required", index=True)
    proxy_mode = Column(String(20), nullable=False, default="auto")
    proxy_id = Column(Integer, ForeignKey("proxy_configs.id", ondelete="SET NULL"), nullable=True)
    sync_enabled = Column(Boolean, nullable=False, default=True)
    sync_interval_seconds = Column(Integer, nullable=False, default=300)
    initial_sync_days = Column(Integer, nullable=False, default=30)
    initial_sync_limit = Column(Integer, nullable=False, default=1)
    last_history_id = Column(String(80), nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    remark = Column(Text, nullable=True)

    proxy = relationship("ProxyConfig", back_populates="accounts")
    aliases = relationship("GmailAlias", back_populates="account", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="account", cascade="all, delete-orphan")
    sync_jobs = relationship("SyncJob", back_populates="account", cascade="all, delete-orphan")


class GmailAlias(TimestampMixin, Base):
    __tablename__ = "gmail_aliases"
    __table_args__ = (UniqueConstraint("account_id", "alias_address", name="uq_alias_account_address"),)

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    alias_address = Column(String(255), nullable=False, index=True)
    pattern = Column(String(255), nullable=False)
    sequence = Column(Integer, nullable=False)
    label = Column(String(120), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    message_count = Column(Integer, nullable=False, default=0)
    last_seen_at = Column(DateTime, nullable=True)

    account = relationship("GmailAccount", back_populates="aliases")
    messages = relationship("Message", back_populates="alias")


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("account_id", "gmail_message_id", name="uq_message_account_gmail_id"),)

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    alias_id = Column(Integer, ForeignKey("gmail_aliases.id", ondelete="SET NULL"), nullable=True, index=True)
    gmail_message_id = Column(String(120), nullable=False, index=True)
    thread_id = Column(String(120), nullable=True, index=True)
    history_id = Column(String(120), nullable=True)
    rfc_message_id = Column(String(500), nullable=True, index=True)
    subject = Column(Text, nullable=True)
    sender = Column(Text, nullable=True, index=True)
    recipients = Column(Text, nullable=True)
    cc = Column(Text, nullable=True)
    received_at = Column(DateTime, nullable=True, index=True)
    internal_date_ms = Column(String(40), nullable=True)
    snippet = Column(Text, nullable=True)
    text_body = Column(Text, nullable=True)
    html_body = Column(Text, nullable=True)
    raw_headers = Column(Text, nullable=True)
    has_attachment = Column(Boolean, nullable=False, default=False, index=True)

    account = relationship("GmailAccount", back_populates="messages")
    alias = relationship("GmailAlias", back_populates="messages")
    attachments = relationship("Attachment", back_populates="message", cascade="all, delete-orphan")


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("message_id", "gmail_attachment_id", "filename", name="uq_attachment_message_gmail_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    gmail_attachment_id = Column(String(255), nullable=False)
    part_id = Column(String(80), nullable=True)
    filename = Column(Text, nullable=False)
    mime_type = Column(String(255), nullable=True)
    size = Column(Integer, nullable=True)
    cached_path = Column(Text, nullable=True)

    message = relationship("Message", back_populates="attachments")


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    key_hash = Column(String(128), unique=True, nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=True)
    account_ids = Column(Text, nullable=True)
    aliases = Column(Text, nullable=True)
    ip_allowlist = Column(Text, nullable=True)
    rate_limit_per_minute = Column(Integer, nullable=False, default=60)
    last_used_at = Column(DateTime, nullable=True)


class OAuthState(TimestampMixin, Base):
    __tablename__ = "oauth_states"

    id = Column(Integer, primary_key=True, index=True)
    state = Column(String(255), unique=True, nullable=False, index=True)
    email_hint = Column(String(255), nullable=True)
    proxy_id = Column(Integer, ForeignKey("proxy_configs.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)


class SyncJob(TimestampMixin, Base):
    __tablename__ = "sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="pending", index=True)
    requested_by = Column(String(80), nullable=False, default="manual")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    fetched_count = Column(Integer, nullable=False, default=0)
    inserted_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    account = relationship("GmailAccount", back_populates="sync_jobs")
    logs = relationship("SyncLog", back_populates="job", cascade="all, delete-orphan")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("sync_jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String(20), nullable=False, default="info")
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    job = relationship("SyncJob", back_populates="logs")
