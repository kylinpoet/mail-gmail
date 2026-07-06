import time
from datetime import UTC, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_api_key
from app.core.database import get_db
from app.models import ApiKey, Attachment, GmailAccount, GmailAlias, Message
from app.schemas import AttachmentPayload, MessageDetail, MessageListItem, MessagePage
from app.services.imap_mail import read_attachment_payload
from app.services.json_helpers import loads_dict, loads_list


router = APIRouter(prefix="/api/v1", tags=["consumer"])
_rate_buckets: Dict[str, List[float]] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _touch_and_limit(db: Session, api_key: ApiKey) -> None:
    now = time.time()
    bucket_key = str(api_key.id)
    window = now - 60
    values = [item for item in _rate_buckets.get(bucket_key, []) if item >= window]
    if len(values) >= api_key.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    values.append(now)
    _rate_buckets[bucket_key] = values
    api_key.last_used_at = _utcnow()
    db.add(api_key)
    db.commit()


def _allowed_account_ids(api_key: ApiKey) -> List[int]:
    return [int(item) for item in loads_list(api_key.account_ids) if str(item).isdigit()]


def _allowed_aliases(api_key: ApiKey) -> List[str]:
    return [str(item).lower() for item in loads_list(api_key.aliases)]


def _account_allowed(api_key: ApiKey, account_id: int) -> bool:
    account_ids = _allowed_account_ids(api_key)
    return not account_ids or account_id in account_ids


def _alias_allowed(api_key: ApiKey, alias_address: Optional[str]) -> bool:
    aliases = _allowed_aliases(api_key)
    return not aliases or (alias_address or "").lower() in aliases


def _message_item(message: Message) -> MessageListItem:
    return MessageListItem(
        id=message.id,
        account_id=message.account_id,
        alias_id=message.alias_id,
        alias_address=message.alias.alias_address if message.alias else None,
        gmail_message_id=message.gmail_message_id,
        thread_id=message.thread_id,
        subject=message.subject,
        sender=message.sender,
        recipients=loads_list(message.recipients),
        received_at=message.received_at,
        snippet=message.snippet,
        has_attachment=message.has_attachment,
    )


def _message_detail(message: Message) -> MessageDetail:
    item = _message_item(message).model_dump()
    item.update(
        {
            "cc": loads_list(message.cc),
            "rfc_message_id": message.rfc_message_id,
            "history_id": message.history_id,
            "text_body": message.text_body,
            "html_body": message.html_body,
            "raw_headers": loads_dict(message.raw_headers),
            "attachments": message.attachments,
        }
    )
    return MessageDetail(**item)


@router.get("/accounts")
def consumer_accounts(
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key),
):
    _touch_and_limit(db, api_key)
    query = db.query(GmailAccount)
    account_ids = _allowed_account_ids(api_key)
    if account_ids:
        query = query.filter(GmailAccount.id.in_(account_ids))
    return [
        {
            "id": account.id,
            "email": account.email,
            "status": account.status,
            "last_sync_at": account.last_sync_at,
            "last_error": account.last_error,
        }
        for account in query.order_by(GmailAccount.id.asc()).all()
    ]


@router.get("/aliases")
def consumer_aliases(
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key),
):
    _touch_and_limit(db, api_key)
    query = db.query(GmailAlias)
    account_ids = _allowed_account_ids(api_key)
    aliases = _allowed_aliases(api_key)
    if account_ids:
        query = query.filter(GmailAlias.account_id.in_(account_ids))
    if aliases:
        query = query.filter(GmailAlias.alias_address.in_(aliases))
    return [
        {
            "id": alias.id,
            "account_id": alias.account_id,
            "alias_address": alias.alias_address,
            "label": alias.label,
            "enabled": alias.enabled,
            "message_count": alias.message_count,
            "last_seen_at": alias.last_seen_at,
        }
        for alias in query.order_by(GmailAlias.alias_address.asc()).all()
    ]


@router.get("/messages", response_model=MessagePage)
def list_consumer_messages(
    account_id: Optional[int] = None,
    alias: Optional[str] = None,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    subject: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    has_attachment: Optional[bool] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[int] = None,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key),
):
    _touch_and_limit(db, api_key)
    query = db.query(Message).options(joinedload(Message.alias)).order_by(Message.id.desc())
    account_ids = _allowed_account_ids(api_key)
    allowed_aliases = _allowed_aliases(api_key)
    if account_ids:
        query = query.filter(Message.account_id.in_(account_ids))
    if account_id:
        if not _account_allowed(api_key, account_id):
            raise HTTPException(status_code=403, detail="account not allowed")
        query = query.filter(Message.account_id == account_id)
    if allowed_aliases:
        query = query.join(GmailAlias, Message.alias_id == GmailAlias.id).filter(GmailAlias.alias_address.in_(allowed_aliases))
    if alias:
        alias = alias.lower()
        if not _alias_allowed(api_key, alias):
            raise HTTPException(status_code=403, detail="alias not allowed")
        query = query.join(GmailAlias, Message.alias_id == GmailAlias.id).filter(GmailAlias.alias_address == alias)
    if cursor:
        query = query.filter(Message.id < cursor)
    if from_:
        query = query.filter(Message.sender.ilike("%" + from_ + "%"))
    if to:
        query = query.filter(Message.recipients.ilike("%" + to + "%"))
    if subject:
        query = query.filter(Message.subject.ilike("%" + subject + "%"))
    if since:
        query = query.filter(Message.received_at >= since)
    if until:
        query = query.filter(Message.received_at <= until)
    if has_attachment is not None:
        query = query.filter(Message.has_attachment.is_(has_attachment))
    if q:
        like = "%" + q + "%"
        query = query.filter(or_(Message.subject.ilike(like), Message.snippet.ilike(like), Message.text_body.ilike(like)))
    rows = query.limit(limit + 1).all()
    items = rows[:limit]
    next_cursor = rows[limit].id if len(rows) > limit else None
    return MessagePage(items=[_message_item(message) for message in items], next_cursor=next_cursor)


@router.get("/messages/{message_id}", response_model=MessageDetail)
def get_consumer_message(
    message_id: int,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key),
):
    _touch_and_limit(db, api_key)
    message = (
        db.query(Message)
        .options(joinedload(Message.alias), joinedload(Message.attachments))
        .filter(Message.id == message_id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="message not found")
    alias_address = message.alias.alias_address if message.alias else None
    if not _account_allowed(api_key, message.account_id) or not _alias_allowed(api_key, alias_address):
        raise HTTPException(status_code=403, detail="message not allowed")
    return _message_detail(message)


@router.get("/messages/{message_id}/attachments/{attachment_id}", response_model=AttachmentPayload)
def read_attachment(
    message_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key),
):
    _touch_and_limit(db, api_key)
    message = (
        db.query(Message)
        .options(joinedload(Message.account), joinedload(Message.alias))
        .filter(Message.id == message_id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="message not found")
    alias_address = message.alias.alias_address if message.alias else None
    if not _account_allowed(api_key, message.account_id) or not _alias_allowed(api_key, alias_address):
        raise HTTPException(status_code=403, detail="message not allowed")
    attachment = (
        db.query(Attachment)
        .filter(Attachment.id == attachment_id, Attachment.message_id == message.id)
        .first()
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="attachment not found")
    data = read_attachment_payload(attachment.cached_path)
    if not data:
        raise HTTPException(status_code=404, detail="attachment payload is not cached")
    return AttachmentPayload(
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        size=attachment.size,
        data_base64url=data,
    )
