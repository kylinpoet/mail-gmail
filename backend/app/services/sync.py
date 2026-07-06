from datetime import UTC, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models import Attachment, GmailAccount, Message, SyncJob, SyncLog
from app.services.aliases import find_alias_for_headers, refresh_alias_stats
from app.services.imap_mail import (
    ImapAuthError,
    ImapConnectionError,
    attachment_storage_path,
    connect_imap,
    fetch_message_raw,
    fetch_uids,
    parse_imap_message,
    test_imap_login,
)
from app.services.json_helpers import dumps
from app.services.proxy import resolve_proxy


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _log(db: Session, job: SyncJob, level: str, message: str, details: Optional[str] = None) -> None:
    db.add(SyncLog(job_id=job.id, account_id=job.account_id, level=level, message=message, details=details))
    db.commit()


def _app_password_for_account(db: Session, account: GmailAccount) -> str:
    app_password = decrypt_secret(account.encrypted_app_password)
    if not app_password:
        account.status = "auth_failed"
        account.last_error = "missing app password"
        db.add(account)
        db.commit()
        raise ImapAuthError("missing app password")
    return app_password


def test_account_access(db: Session, account: GmailAccount) -> Dict[str, str]:
    app_password = _app_password_for_account(db, account)
    proxy = resolve_proxy(db, account)
    profile = test_imap_login(account.email, app_password, proxy)
    account.status = "active"
    account.last_error = None
    db.add(account)
    db.commit()
    return profile


def _existing_message(db: Session, account_id: int, gmail_message_id: str) -> Optional[Message]:
    return (
        db.query(Message)
        .filter(Message.account_id == account_id, Message.gmail_message_id == gmail_message_id)
        .first()
    )


def _upsert_message(db: Session, account: GmailAccount, parsed: Dict) -> Tuple[Message, bool]:
    gmail_id = parsed["gmail_message_id"]
    existing = _existing_message(db, account.id, gmail_id)
    alias = find_alias_for_headers(db, account.id, parsed["lower_headers"])
    is_new = existing is None
    message = existing or Message(account_id=account.id, gmail_message_id=gmail_id)
    message.alias_id = alias.id if alias else None
    message.thread_id = parsed["thread_id"]
    message.history_id = parsed["history_id"]
    message.rfc_message_id = parsed["rfc_message_id"]
    message.subject = parsed["subject"]
    message.sender = parsed["sender"]
    message.recipients = dumps(parsed["recipients"])
    message.cc = dumps(parsed["cc"])
    message.received_at = parsed["received_at"]
    message.internal_date_ms = parsed["internal_date_ms"]
    message.snippet = parsed["snippet"]
    message.text_body = parsed["text_body"]
    message.html_body = parsed["html_body"]
    message.raw_headers = dumps(parsed["raw_headers"])
    message.has_attachment = parsed["has_attachment"]
    db.add(message)
    db.flush()
    if existing is not None:
        db.query(Attachment).filter(Attachment.message_id == message.id).delete(synchronize_session=False)
    for item in parsed["attachments"]:
        cached_path = attachment_storage_path(account.id, gmail_id, item["filename"], item.get("data") or b"")
        with open(cached_path, "wb") as handle:
            handle.write(item.get("data") or b"")
        db.add(
            Attachment(
                message_id=message.id,
                gmail_attachment_id=item["gmail_attachment_id"],
                part_id=item.get("part_id"),
                filename=item["filename"],
                mime_type=item.get("mime_type"),
                size=item.get("size"),
                cached_path=cached_path,
            )
        )
    return message, is_new


def sync_account(
    db: Session,
    account_id: int,
    requested_by: str = "manual",
    limit_override: Optional[int] = None,
) -> SyncJob:
    account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
    if not account:
        raise ValueError("account not found")
    job = SyncJob(account_id=account.id, status="running", requested_by=requested_by, started_at=_utcnow())
    db.add(job)
    db.commit()
    db.refresh(job)
    fetched = 0
    inserted = 0
    try:
        if account.status == "disabled" or not account.sync_enabled:
            raise ValueError("account sync is disabled")
        app_password = _app_password_for_account(db, account)
        proxy = resolve_proxy(db, account)
        client = connect_imap(account.email, app_password, proxy)
        try:
            message_ids = fetch_uids(
                client,
                account.last_history_id,
                account.initial_sync_days,
                limit_override or account.initial_sync_limit,
            )
            for message_id in message_ids:
                raw = fetch_message_raw(client, message_id)
                parsed = parse_imap_message(message_id, raw)
                _, is_new = _upsert_message(db, account, parsed)
                fetched += 1
                inserted += 1 if is_new else 0
            if message_ids:
                account.last_history_id = max(message_ids, key=lambda value: int(value) if value.isdigit() else 0)
        finally:
            try:
                client.logout()
            except Exception:
                pass
        account.last_sync_at = _utcnow()
        account.status = "active"
        account.last_error = None
        job.status = "success"
    except ImapAuthError as exc:
        account.status = "auth_failed"
        account.last_error = str(exc)
        job.status = "failed"
        job.error = str(exc)
        _log(db, job, "error", "IMAP auth failed", str(exc))
    except ImapConnectionError as exc:
        account.status = "proxy_failed" if resolve_proxy(db, account) else account.status
        account.last_error = str(exc)
        job.status = "failed"
        job.error = str(exc)
        _log(db, job, "error", "IMAP connection failed", str(exc))
    except Exception as exc:
        account.last_error = str(exc)
        job.status = "failed"
        job.error = str(exc)
        _log(db, job, "error", "sync failed", str(exc))
    finally:
        job.fetched_count = fetched
        job.inserted_count = inserted
        job.finished_at = _utcnow()
        db.add(account)
        db.add(job)
        db.commit()
        refresh_alias_stats(db, account.id)
        db.refresh(job)
    return job
