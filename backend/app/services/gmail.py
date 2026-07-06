import base64
from datetime import UTC, datetime
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.models import ProxyConfig
from app.services.proxy import build_proxy_url


GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailApiError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super(GmailApiError, self).__init__(message)
        self.status_code = status_code


def _request(
    method: str,
    access_token: str,
    path: str,
    proxy: Optional[ProxyConfig],
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = {"Authorization": "Bearer " + access_token}
    url = GMAIL_API_BASE + path
    proxy_url = build_proxy_url(proxy)
    try:
        with httpx.Client(proxy=proxy_url, timeout=60) as client:
            response = client.request(method, url, headers=headers, params=params)
    except Exception as exc:
        raise GmailApiError(str(exc))
    if response.status_code >= 400:
        raise GmailApiError(response.text, response.status_code)
    return response.json()


def list_messages(
    access_token: str,
    proxy: Optional[ProxyConfig],
    q: Optional[str] = None,
    page_token: Optional[str] = None,
    max_results: int = 100,
) -> Dict[str, Any]:
    params = {"maxResults": min(max_results, 500)}
    if q:
        params["q"] = q
    if page_token:
        params["pageToken"] = page_token
    return _request("GET", access_token, "/users/me/messages", proxy, params=params)


def get_message(access_token: str, proxy: Optional[ProxyConfig], message_id: str) -> Dict[str, Any]:
    return _request(
        "GET",
        access_token,
        "/users/me/messages/%s" % message_id,
        proxy,
        params={"format": "full"},
    )


def list_history(
    access_token: str,
    proxy: Optional[ProxyConfig],
    start_history_id: str,
    page_token: Optional[str] = None,
) -> Dict[str, Any]:
    params = {"startHistoryId": start_history_id, "historyTypes": "messageAdded"}
    if page_token:
        params["pageToken"] = page_token
    return _request("GET", access_token, "/users/me/history", proxy, params=params)


def get_attachment_data(
    access_token: str,
    proxy: Optional[ProxyConfig],
    message_id: str,
    attachment_id: str,
) -> Dict[str, Any]:
    return _request(
        "GET",
        access_token,
        "/users/me/messages/%s/attachments/%s" % (message_id, attachment_id),
        proxy,
    )


def _decode_body(data: Optional[str]) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _header_map(payload: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    headers = payload.get("headers") or []
    raw = {}
    lower = {}
    for item in headers:
        name = item.get("name")
        value = item.get("value", "")
        if not name:
            continue
        raw[name] = value
        key = name.lower()
        lower[key] = (lower[key] + ", " + value) if key in lower else value
    return raw, lower


def _parse_date(headers: Dict[str, str], internal_date_ms: Optional[str]) -> Optional[datetime]:
    if internal_date_ms:
        try:
            return datetime.fromtimestamp(int(internal_date_ms) / 1000.0, UTC).replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
    date_header = headers.get("date")
    if not date_header:
        return None
    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(tz=None).replace(tzinfo=None)
    return parsed


def _parse_addresses(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [addr for _, addr in getaddresses([value]) if addr]


def _walk_parts(part: Dict[str, Any], texts: List[str], htmls: List[str], attachments: List[Dict[str, Any]]) -> None:
    mime_type = part.get("mimeType")
    filename = part.get("filename") or ""
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId")
    data = body.get("data")
    if filename and attachment_id:
        attachments.append(
            {
                "gmail_attachment_id": attachment_id,
                "part_id": part.get("partId"),
                "filename": filename,
                "mime_type": mime_type,
                "size": body.get("size"),
            }
        )
    if data and mime_type == "text/plain":
        texts.append(_decode_body(data))
    elif data and mime_type == "text/html":
        htmls.append(_decode_body(data))
    for child in part.get("parts") or []:
        _walk_parts(child, texts, htmls, attachments)


def parse_message(resource: Dict[str, Any]) -> Dict[str, Any]:
    payload = resource.get("payload") or {}
    raw_headers, headers = _header_map(payload)
    texts = []
    htmls = []
    attachments = []
    _walk_parts(payload, texts, htmls, attachments)
    internal_date = resource.get("internalDate")
    return {
        "gmail_message_id": resource.get("id"),
        "thread_id": resource.get("threadId"),
        "history_id": resource.get("historyId"),
        "rfc_message_id": headers.get("message-id"),
        "subject": headers.get("subject"),
        "sender": headers.get("from"),
        "recipients": _parse_addresses(headers.get("to")),
        "cc": _parse_addresses(headers.get("cc")),
        "received_at": _parse_date(headers, internal_date),
        "internal_date_ms": internal_date,
        "snippet": resource.get("snippet"),
        "text_body": "\n".join([text for text in texts if text]).strip() or None,
        "html_body": "\n".join([html for html in htmls if html]).strip() or None,
        "raw_headers": raw_headers,
        "lower_headers": headers,
        "attachments": attachments,
        "has_attachment": bool(attachments),
    }
