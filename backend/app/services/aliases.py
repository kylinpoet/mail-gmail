import re
import secrets
import string
from datetime import datetime
from email.utils import getaddresses
from typing import Dict, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GmailAccount, GmailAlias, Message
from app.schemas import AliasGenerateRequest


ALIAS_HEADER_NAMES = ("to", "cc", "delivered-to", "x-original-to")
RANDOM_ALPHABET = string.ascii_lowercase + string.digits


def _safe_tag(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "alias"


def build_alias_address(account_email: str, tag: str) -> str:
    local, domain = account_email.lower().split("@", 1)
    local = local.split("+", 1)[0]
    return "%s+%s@%s" % (local, _safe_tag(tag), domain)


def _random_token(length: int) -> str:
    length = max(1, min(length, 64))
    return "".join(secrets.choice(RANDOM_ALPHABET) for _ in range(length))


def render_alias_tag(pattern: str, seq: int) -> str:
    if not pattern:
        pattern = "alias-{n}"

    used_counter = False

    def replace_counter(match):
        nonlocal used_counter
        used_counter = True
        width = len(match.group(1) or "")
        return str(seq).zfill(width) if width else str(seq)

    tag = re.sub(r"\{n(?::(0+))?\}", replace_counter, pattern)

    def replace_random(match):
        length = int(match.group(1))
        return _random_token(length)

    tag = re.sub(r"\{rand:(\d{1,2})\}", replace_random, tag)
    if not used_counter and "{rand:" not in pattern:
        tag = "%s-%s" % (tag, seq)
    return tag


def generate_aliases(db: Session, account: GmailAccount, payload: AliasGenerateRequest):
    db.query(GmailAlias).filter(GmailAlias.account_id == account.id).delete(synchronize_session=False)
    created = []
    seen = set()
    for seq in range(1, payload.count + 1):
        address = None
        for _ in range(10):
            tag = render_alias_tag(payload.pattern, seq)
            address = build_alias_address(account.email, tag)
            if address not in seen:
                break
        if not address:
            continue
        if address in seen:
            continue
        seen.add(address)
        alias = GmailAlias(
            account_id=account.id,
            alias_address=address,
            pattern=payload.pattern,
            sequence=seq,
            label=payload.label,
            enabled=True,
        )
        db.add(alias)
        created.append(alias)
    db.commit()
    for alias in created:
        db.refresh(alias)
    refresh_alias_stats(db, account.id)
    return created


def _addresses_from_headers(headers: Dict[str, str], names: Iterable[str]):
    values = []
    for name in names:
        value = headers.get(name)
        if value:
            values.append(value)
    return [addr.lower() for _, addr in getaddresses(values) if addr]


def find_alias_for_headers(db: Session, account_id: int, headers: Dict[str, str]) -> Optional[GmailAlias]:
    addresses = set(_addresses_from_headers(headers, ALIAS_HEADER_NAMES))
    if not addresses:
        return None
    aliases = (
        db.query(GmailAlias)
        .filter(GmailAlias.account_id == account_id, GmailAlias.enabled.is_(True))
        .all()
    )
    for alias in aliases:
        if alias.alias_address.lower() in addresses:
            return alias
    return None


def refresh_alias_stats(db: Session, account_id: int) -> None:
    aliases = db.query(GmailAlias).filter(GmailAlias.account_id == account_id).all()
    for alias in aliases:
        alias.message_count = db.query(Message).filter(Message.alias_id == alias.id).count()
        last_seen = db.query(func.max(Message.received_at)).filter(Message.alias_id == alias.id).scalar()
        alias.last_seen_at = last_seen if isinstance(last_seen, datetime) else None
        db.add(alias)
    db.commit()
