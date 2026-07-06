import time
from datetime import UTC, datetime
from typing import Optional
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret
from app.models import GmailAccount, ProxyConfig
from app.schemas import ProxyCreate, ProxyTestResponse, ProxyUpdate


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def proxy_to_public(proxy: ProxyConfig) -> dict:
    return {
        "id": proxy.id,
        "name": proxy.name,
        "type": proxy.type,
        "host": proxy.host,
        "port": proxy.port,
        "username": proxy.username,
        "enabled": proxy.enabled,
        "is_global": proxy.is_global,
        "timeout_seconds": proxy.timeout_seconds,
        "region": proxy.region,
        "remark": proxy.remark,
        "last_test_ok": proxy.last_test_ok,
        "last_test_at": proxy.last_test_at,
        "last_test_error": proxy.last_test_error,
        "created_at": proxy.created_at,
        "updated_at": proxy.updated_at,
        "password_configured": bool(proxy.encrypted_password),
    }


def build_proxy_url(proxy: Optional[ProxyConfig]) -> Optional[str]:
    if not proxy or not proxy.enabled:
        return None
    auth = ""
    if proxy.username:
        auth = quote(proxy.username, safe="")
        password = decrypt_secret(proxy.encrypted_password)
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return "%s://%s%s:%s" % (proxy.type, auth, proxy.host, proxy.port)


def create_proxy(db: Session, payload: ProxyCreate) -> ProxyConfig:
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
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


def update_proxy(db: Session, proxy: ProxyConfig, payload: ProxyUpdate) -> ProxyConfig:
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        proxy.encrypted_password = encrypt_secret(data.pop("password"))
    for key, value in data.items():
        setattr(proxy, key, value)
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


def resolve_proxy(db: Session, account: Optional[GmailAccount] = None) -> Optional[ProxyConfig]:
    if account and account.proxy_mode == "direct":
        return None
    if account and account.proxy and account.proxy.enabled:
        return account.proxy
    pool_proxy = (
        db.query(ProxyConfig)
        .filter(ProxyConfig.enabled.is_(True), ProxyConfig.is_global.is_(False))
        .order_by(ProxyConfig.id.asc())
        .first()
    )
    if pool_proxy:
        return pool_proxy
    return (
        db.query(ProxyConfig)
        .filter(ProxyConfig.enabled.is_(True), ProxyConfig.is_global.is_(True))
        .order_by(ProxyConfig.id.asc())
        .first()
    )


def test_proxy_connectivity(proxy: Optional[ProxyConfig]) -> ProxyTestResponse:
    start = time.time()
    proxy_url = build_proxy_url(proxy)
    try:
        with httpx.Client(proxy=proxy_url, timeout=proxy.timeout_seconds if proxy else 20) as client:
            response = client.get("https://www.gstatic.com/generate_204")
        ok = response.status_code in (200, 204, 301, 302)
        error = None if ok else "unexpected status %s" % response.status_code
    except Exception as exc:  # pragma: no cover - depends on network
        ok = False
        error = str(exc)
    elapsed_ms = int((time.time() - start) * 1000)
    return ProxyTestResponse(ok=ok, error=error, elapsed_ms=elapsed_ms)


def test_and_store_proxy(db: Session, proxy: ProxyConfig) -> ProxyTestResponse:
    result = test_proxy_connectivity(proxy)
    proxy.last_test_ok = result.ok
    proxy.last_test_error = result.error
    proxy.last_test_at = _utcnow()
    db.add(proxy)
    db.commit()
    return result
