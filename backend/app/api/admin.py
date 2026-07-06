import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.security import encrypt_secret, generate_api_key, hash_secret
from app.models import ApiKey, GmailAccount, GmailAlias, Message, ProxyConfig, SyncJob
from app.schemas import (
    AccountCreate,
    AccountRead,
    AccountTestResponse,
    AccountUpdate,
    AliasBatchRequest,
    AliasBatchUpdateRequest,
    AliasGenerateRequest,
    AliasRead,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    MessageBatchRequest,
    ProxyCreate,
    ProxyImapTestResponse,
    ProxyRead,
    ProxyTestResponse,
    ProxyUpdate,
    SyncRequest,
    SyncJobRead,
)
from app.services.aliases import generate_aliases, refresh_alias_stats
from app.services.imap_mail import diagnose_imap_proxy, normalize_app_password
from app.services.json_helpers import dumps, loads_dict, loads_list
from app.services.proxy import create_proxy, proxy_to_public, test_and_store_proxy, test_proxy_connectivity, update_proxy
from app.services.sync import sync_account, test_account_access


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _account_read(account: GmailAccount) -> dict:
    return {
        "id": account.id,
        "email": account.email,
        "auth_type": account.auth_type,
        "google_subject": account.google_subject,
        "scope": account.scope,
        "status": account.status,
        "proxy_mode": account.proxy_mode,
        "proxy_id": account.proxy_id,
        "sync_enabled": account.sync_enabled,
        "sync_interval_seconds": account.sync_interval_seconds,
        "initial_sync_days": account.initial_sync_days,
        "initial_sync_limit": account.initial_sync_limit,
        "last_history_id": account.last_history_id,
        "last_sync_at": account.last_sync_at,
        "last_error": account.last_error,
        "remark": account.remark,
        "app_password_configured": bool(account.encrypted_app_password),
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _api_key_read(api_key: ApiKey) -> dict:
    return {
        "id": api_key.id,
        "name": api_key.name,
        "active": api_key.active,
        "account_ids": loads_list(api_key.account_ids),
        "aliases": loads_list(api_key.aliases),
        "ip_allowlist": loads_list(api_key.ip_allowlist),
        "rate_limit_per_minute": api_key.rate_limit_per_minute,
        "last_used_at": api_key.last_used_at,
        "created_at": api_key.created_at,
        "updated_at": api_key.updated_at,
    }


def _delete_local_messages(db: Session, messages: List[Message]) -> dict:
    deleted_ids = [message.id for message in messages]
    account_ids = sorted({message.account_id for message in messages})
    cached_paths = [
        attachment.cached_path
        for message in messages
        for attachment in message.attachments
        if attachment.cached_path
    ]
    for message in messages:
        db.delete(message)
    db.commit()
    for account_id in account_ids:
        refresh_alias_stats(db, account_id)

    removed_files = 0
    file_errors = []
    for path in cached_paths:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
                removed_files += 1
        except OSError as exc:
            file_errors.append({"path": path, "error": str(exc)})
    return {
        "ok": True,
        "deleted_ids": deleted_ids,
        "deleted_count": len(deleted_ids),
        "removed_cached_files": removed_files,
        "file_errors": file_errors,
    }


@router.get("/health")
def admin_health() -> dict:
    return {"ok": True, "app": settings.app_name}


@router.get("/accounts", response_model=List[AccountRead])
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(GmailAccount).order_by(GmailAccount.id.desc()).all()
    return [_account_read(account) for account in accounts]


@router.post("/accounts", response_model=AccountRead)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    if payload.proxy_id is not None and not db.query(ProxyConfig).filter(ProxyConfig.id == payload.proxy_id).first():
        raise HTTPException(status_code=404, detail="proxy not found")
    email = str(payload.email).lower()
    account = db.query(GmailAccount).filter(GmailAccount.email == email).first()
    if not account:
        account = GmailAccount(email=email)
    account.auth_type = "app_password"
    account.encrypted_app_password = encrypt_secret(normalize_app_password(payload.app_password))
    account.encrypted_refresh_token = None
    account.google_subject = None
    account.scope = "imap.gmail.com:993"
    account.status = "active"
    account.proxy_mode = "fixed" if payload.proxy_id else payload.proxy_mode
    if account.proxy_mode == "direct":
        account.proxy_id = None
    else:
        account.proxy_id = payload.proxy_id
    account.sync_enabled = payload.sync_enabled
    account.sync_interval_seconds = payload.sync_interval_seconds
    account.initial_sync_days = payload.initial_sync_days
    account.initial_sync_limit = payload.initial_sync_limit
    account.remark = payload.remark
    account.last_error = None
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account_read(account)


@router.patch("/accounts/{account_id}", response_model=AccountRead)
def patch_account(account_id: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("proxy_id") is not None and not db.query(ProxyConfig).filter(ProxyConfig.id == data["proxy_id"]).first():
        raise HTTPException(status_code=404, detail="proxy not found")
    if "app_password" in data:
        account.encrypted_app_password = encrypt_secret(normalize_app_password(data.pop("app_password")))
        account.status = "active"
        account.last_error = None
    if data.get("proxy_id") is not None:
        data["proxy_mode"] = "fixed"
    if data.get("proxy_mode") == "direct":
        data["proxy_id"] = None
    for key, value in data.items():
        setattr(account, key, value)
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account_read(account)


@router.post("/accounts/{account_id}/test", response_model=AccountTestResponse)
def test_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    try:
        profile = test_account_access(db, account)
        return AccountTestResponse(ok=True, email=profile.get("email"))
    except Exception as exc:
        return AccountTestResponse(ok=False, error=str(exc))


@router.post("/accounts/{account_id}/sync", response_model=SyncJobRead)
def run_sync(account_id: int, payload: Optional[SyncRequest] = None, db: Session = Depends(get_db)):
    if not db.query(GmailAccount).filter(GmailAccount.id == account_id).first():
        raise HTTPException(status_code=404, detail="account not found")
    return sync_account(db, account_id, requested_by="manual", limit_override=payload.limit if payload else 1)


@router.post("/accounts/{account_id}/revoke", response_model=AccountRead)
def revoke_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    account.encrypted_app_password = None
    account.status = "auth_failed"
    account.sync_enabled = False
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account_read(account)


@router.get("/accounts/{account_id}/aliases", response_model=List[AliasRead])
def list_account_aliases(account_id: int, db: Session = Depends(get_db)):
    return (
        db.query(GmailAlias)
        .filter(GmailAlias.account_id == account_id)
        .order_by(GmailAlias.sequence.asc())
        .all()
    )


@router.post("/accounts/{account_id}/aliases/generate", response_model=List[AliasRead])
def generate_account_aliases(account_id: int, payload: AliasGenerateRequest, db: Session = Depends(get_db)):
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return generate_aliases(db, account, payload)


def _query_account_aliases(db: Session, account_id: int, ids: List[int]):
    aliases = (
        db.query(GmailAlias)
        .filter(GmailAlias.account_id == account_id, GmailAlias.id.in_(ids))
        .all()
    )
    found_ids = {alias.id for alias in aliases}
    missing = [alias_id for alias_id in ids if alias_id not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail={"missing_alias_ids": missing})
    return aliases


@router.patch("/accounts/{account_id}/aliases/batch", response_model=List[AliasRead])
def update_account_aliases(account_id: int, payload: AliasBatchUpdateRequest, db: Session = Depends(get_db)):
    if not db.query(GmailAccount).filter(GmailAccount.id == account_id).first():
        raise HTTPException(status_code=404, detail="account not found")
    aliases = _query_account_aliases(db, account_id, payload.ids)
    for alias in aliases:
        alias.enabled = payload.enabled
        db.add(alias)
    db.commit()
    return (
        db.query(GmailAlias)
        .filter(GmailAlias.account_id == account_id, GmailAlias.id.in_(payload.ids))
        .order_by(GmailAlias.sequence.asc())
        .all()
    )


@router.delete("/accounts/{account_id}/aliases/batch")
def delete_account_aliases(account_id: int, payload: AliasBatchRequest, db: Session = Depends(get_db)):
    if not db.query(GmailAccount).filter(GmailAccount.id == account_id).first():
        raise HTTPException(status_code=404, detail="account not found")
    aliases = _query_account_aliases(db, account_id, payload.ids)
    for alias in aliases:
        db.delete(alias)
    db.commit()
    return {"ok": True, "deleted_ids": payload.ids}


@router.delete("/accounts/{account_id}/aliases/{alias_id}")
def delete_account_alias(account_id: int, alias_id: int, db: Session = Depends(get_db)):
    alias = (
        db.query(GmailAlias)
        .filter(GmailAlias.account_id == account_id, GmailAlias.id == alias_id)
        .first()
    )
    if not alias:
        raise HTTPException(status_code=404, detail="alias not found")
    db.delete(alias)
    db.commit()
    return {"ok": True, "deleted_id": alias_id}


@router.get("/proxies", response_model=List[ProxyRead])
def list_proxies(db: Session = Depends(get_db)):
    proxies = db.query(ProxyConfig).order_by(ProxyConfig.id.desc()).all()
    return [proxy_to_public(proxy) for proxy in proxies]


@router.post("/proxies", response_model=ProxyRead)
def create_proxy_route(payload: ProxyCreate, db: Session = Depends(get_db)):
    proxy = create_proxy(db, payload)
    return proxy_to_public(proxy)


@router.patch("/proxies/{proxy_id}", response_model=ProxyRead)
def patch_proxy(proxy_id: int, payload: ProxyUpdate, db: Session = Depends(get_db)):
    proxy = db.query(ProxyConfig).filter(ProxyConfig.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="proxy not found")
    proxy = update_proxy(db, proxy, payload)
    return proxy_to_public(proxy)


@router.delete("/proxies/{proxy_id}")
def delete_proxy(proxy_id: int, db: Session = Depends(get_db)):
    proxy = db.query(ProxyConfig).filter(ProxyConfig.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="proxy not found")
    affected_accounts = (
        db.query(GmailAccount)
        .filter(GmailAccount.proxy_id == proxy_id)
        .all()
    )
    affected_account_ids = [account.id for account in affected_accounts]
    for account in affected_accounts:
        account.proxy_id = None
        account.proxy_mode = "auto"
        db.add(account)
    db.delete(proxy)
    db.commit()
    return {"ok": True, "deleted_id": proxy_id, "affected_account_ids": affected_account_ids}


@router.post("/proxies/test", response_model=ProxyTestResponse)
def test_proxy_payload(payload: ProxyCreate):
    proxy = ProxyConfig(
        name=payload.name,
        type=payload.type,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        encrypted_password=encrypt_secret(payload.password),
        enabled=payload.enabled,
        is_global=payload.is_global,
        timeout_seconds=payload.timeout_seconds,
        region=payload.region,
        remark=payload.remark,
    )
    return test_proxy_connectivity(proxy)


@router.post("/proxies/test-imap", response_model=ProxyImapTestResponse)
def test_proxy_payload_imap(payload: ProxyCreate):
    proxy = ProxyConfig(
        name=payload.name,
        type=payload.type,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        encrypted_password=encrypt_secret(payload.password),
        enabled=payload.enabled,
        is_global=payload.is_global,
        timeout_seconds=payload.timeout_seconds,
        region=payload.region,
        remark=payload.remark,
    )
    return diagnose_imap_proxy(proxy)


@router.post("/proxies/{proxy_id}/test", response_model=ProxyTestResponse)
def test_saved_proxy(proxy_id: int, db: Session = Depends(get_db)):
    proxy = db.query(ProxyConfig).filter(ProxyConfig.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="proxy not found")
    return test_and_store_proxy(db, proxy)


@router.post("/proxies/{proxy_id}/test-imap", response_model=ProxyImapTestResponse)
def test_saved_proxy_imap(proxy_id: int, db: Session = Depends(get_db)):
    proxy = db.query(ProxyConfig).filter(ProxyConfig.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="proxy not found")
    return diagnose_imap_proxy(proxy)


@router.post("/api-keys", response_model=ApiKeyCreated)
def create_api_key(payload: ApiKeyCreate, db: Session = Depends(get_db)):
    secret = generate_api_key()
    api_key = ApiKey(
        name=payload.name,
        key_hash=hash_secret(secret),
        account_ids=dumps(payload.account_ids or []),
        aliases=dumps([str(item).lower() for item in payload.aliases or []]),
        ip_allowlist=dumps(payload.ip_allowlist or []),
        rate_limit_per_minute=payload.rate_limit_per_minute,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    data = _api_key_read(api_key)
    data["api_key"] = secret
    return data


@router.get("/api-keys", response_model=List[ApiKeyRead])
def list_api_keys(db: Session = Depends(get_db)):
    return [_api_key_read(item) for item in db.query(ApiKey).order_by(ApiKey.id.desc()).all()]


@router.patch("/api-keys/{api_key_id}", response_model=ApiKeyRead)
def toggle_api_key(api_key_id: int, active: bool = Query(...), db: Session = Depends(get_db)):
    api_key = db.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="api key not found")
    api_key.active = active
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return _api_key_read(api_key)


@router.delete("/api-keys/{api_key_id}")
def delete_api_key(api_key_id: int, db: Session = Depends(get_db)):
    api_key = db.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="api key not found")
    db.delete(api_key)
    db.commit()
    return {"ok": True, "deleted_id": api_key_id}


@router.get("/sync-jobs", response_model=List[SyncJobRead])
def list_sync_jobs(db: Session = Depends(get_db), account_id: Optional[int] = None):
    query = db.query(SyncJob)
    if account_id:
        query = query.filter(SyncJob.account_id == account_id)
    return query.order_by(SyncJob.id.desc()).limit(100).all()


@router.get("/messages")
def list_admin_messages(
    account_id: Optional[int] = None,
    alias: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Message).order_by(Message.id.desc())
    if account_id:
        query = query.filter(Message.account_id == account_id)
    if alias:
        query = query.join(GmailAlias, Message.alias_id == GmailAlias.id).filter(GmailAlias.alias_address == alias.lower())
    if q:
        like = "%" + q + "%"
        query = query.filter((Message.subject.ilike(like)) | (Message.sender.ilike(like)) | (Message.text_body.ilike(like)))
    messages = query.limit(limit).all()
    return [
        {
            "id": message.id,
            "account_id": message.account_id,
            "alias_address": message.alias.alias_address if message.alias else None,
            "gmail_message_id": message.gmail_message_id,
            "subject": message.subject,
            "sender": message.sender,
            "recipients": loads_list(message.recipients),
            "received_at": message.received_at,
            "snippet": message.snippet,
            "has_attachment": message.has_attachment,
        }
        for message in messages
    ]


@router.delete("/messages/batch")
def delete_admin_messages_batch(payload: MessageBatchRequest, db: Session = Depends(get_db)):
    messages = db.query(Message).filter(Message.id.in_(payload.ids)).all()
    found_ids = {message.id for message in messages}
    missing_ids = [message_id for message_id in payload.ids if message_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail={"missing_message_ids": missing_ids})
    return _delete_local_messages(db, messages)


@router.get("/messages/{message_id}")
def get_admin_message(message_id: int, db: Session = Depends(get_db)):
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="message not found")
    return {
        "id": message.id,
        "account_id": message.account_id,
        "alias_address": message.alias.alias_address if message.alias else None,
        "gmail_message_id": message.gmail_message_id,
        "thread_id": message.thread_id,
        "history_id": message.history_id,
        "rfc_message_id": message.rfc_message_id,
        "subject": message.subject,
        "sender": message.sender,
        "recipients": loads_list(message.recipients),
        "cc": loads_list(message.cc),
        "received_at": message.received_at,
        "snippet": message.snippet,
        "text_body": message.text_body,
        "html_body": message.html_body,
        "raw_headers": loads_dict(message.raw_headers),
        "has_attachment": message.has_attachment,
        "attachments": [
            {
                "id": attachment.id,
                "filename": attachment.filename,
                "mime_type": attachment.mime_type,
                "size": attachment.size,
            }
            for attachment in message.attachments
        ],
    }


@router.delete("/messages/{message_id}")
def delete_admin_message(message_id: int, db: Session = Depends(get_db)):
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="message not found")
    result = _delete_local_messages(db, [message])
    result["deleted_id"] = message_id
    return result
