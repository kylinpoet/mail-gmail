import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import OAuthState, ProxyConfig
from app.services.proxy import build_proxy_url


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
PROFILE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"


class OAuthError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def create_oauth_state(db: Session, email_hint: Optional[str], proxy_id: Optional[int]) -> OAuthState:
    state = secrets.token_urlsafe(32)
    record = OAuthState(
        state=state,
        email_hint=email_hint,
        proxy_id=proxy_id,
        expires_at=_utcnow() + timedelta(seconds=settings.oauth_state_ttl_seconds),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def consume_oauth_state(db: Session, state: str) -> OAuthState:
    record = db.query(OAuthState).filter(OAuthState.state == state).first()
    if not record:
        raise OAuthError("invalid oauth state")
    if record.consumed_at is not None:
        raise OAuthError("oauth state already consumed")
    if record.expires_at < _utcnow():
        raise OAuthError("oauth state expired")
    record.consumed_at = _utcnow()
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def build_authorization_url(state: str, email_hint: Optional[str] = None) -> str:
    if not settings.google_client_id:
        raise OAuthError("GOOGLE_CLIENT_ID is not configured")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if email_hint:
        params["login_hint"] = email_hint
    return AUTH_ENDPOINT + "?" + urlencode(params)


def _post_token(data: Dict[str, str], proxy: Optional[ProxyConfig]) -> Dict[str, Any]:
    proxy_url = build_proxy_url(proxy)
    try:
        with httpx.Client(proxy=proxy_url, timeout=30) as client:
            response = client.post(TOKEN_ENDPOINT, data=data)
    except Exception as exc:
        raise OAuthError(str(exc))
    if response.status_code >= 400:
        raise OAuthError(response.text)
    return response.json()


def exchange_code_for_token(code: str, proxy: Optional[ProxyConfig] = None) -> Dict[str, Any]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise OAuthError("Google OAuth client is not configured")
    return _post_token(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        proxy,
    )


def refresh_access_token(refresh_token: str, proxy: Optional[ProxyConfig] = None) -> Dict[str, Any]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise OAuthError("Google OAuth client is not configured")
    return _post_token(
        {
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        },
        proxy,
    )


def get_gmail_profile(access_token: str, proxy: Optional[ProxyConfig] = None) -> Dict[str, Any]:
    proxy_url = build_proxy_url(proxy)
    headers = {"Authorization": "Bearer " + access_token}
    try:
        with httpx.Client(proxy=proxy_url, timeout=30) as client:
            response = client.get(PROFILE_ENDPOINT, headers=headers)
    except Exception as exc:
        raise OAuthError(str(exc))
    if response.status_code >= 400:
        raise OAuthError(response.text)
    return response.json()


def get_token_info(access_token: str, proxy: Optional[ProxyConfig] = None) -> Dict[str, Any]:
    proxy_url = build_proxy_url(proxy)
    try:
        with httpx.Client(proxy=proxy_url, timeout=30) as client:
            response = client.get(TOKENINFO_ENDPOINT, params={"access_token": access_token})
    except Exception as exc:
        raise OAuthError(str(exc))
    if response.status_code >= 400:
        raise OAuthError(response.text)
    return response.json()


def revoke_token(token: str, proxy: Optional[ProxyConfig] = None) -> None:
    proxy_url = build_proxy_url(proxy)
    with httpx.Client(proxy=proxy_url, timeout=30) as client:
        client.post(REVOKE_ENDPOINT, params={"token": token})
