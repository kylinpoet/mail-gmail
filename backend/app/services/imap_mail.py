import base64
import hashlib
import imaplib
import os
import socket
import ssl
import time
from datetime import UTC, datetime, timedelta
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from typing import Dict, List, Optional

import socks

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models import ProxyConfig


IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IMAP_CONNECT_ATTEMPTS = 3


class ImapAuthError(Exception):
    pass


class ImapConnectionError(Exception):
    pass


def _is_transient_connection_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "unexpected_eof_while_reading",
            "connection reset",
            "connection aborted",
            "connection closed",
            "timed out",
            "temporarily unavailable",
        )
    )


def normalize_app_password(value: str) -> str:
    return "".join(value.split())


def _proxy_auth_header(proxy: ProxyConfig) -> Optional[str]:
    if not proxy.username:
        return None
    password = decrypt_secret(proxy.encrypted_password) or ""
    raw = ("%s:%s" % (proxy.username, password)).encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _create_http_tunnel(proxy: ProxyConfig, host: str, port: int, timeout: int) -> socket.socket:
    sock = socket.create_connection((proxy.host, proxy.port), timeout=timeout)
    sock.settimeout(timeout)
    request_lines = [
        "CONNECT %s:%s HTTP/1.1" % (host, port),
        "Host: %s:%s" % (host, port),
        "Proxy-Connection: Keep-Alive",
    ]
    auth = _proxy_auth_header(proxy)
    if auth:
        request_lines.append("Proxy-Authorization: %s" % auth)
    request = ("\r\n".join(request_lines) + "\r\n\r\n").encode("ascii")
    try:
        sock.sendall(request)
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                raise ImapConnectionError("HTTP proxy closed connection before CONNECT response")
            buffer += chunk
            if len(buffer) > 65536:
                raise ImapConnectionError("HTTP proxy CONNECT response is too large")
    except Exception:
        sock.close()
        raise

    header_text = buffer.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1", errors="replace")
    status_line = header_text.splitlines()[0] if header_text else ""
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        sock.close()
        raise ImapConnectionError("Proxy did not return a valid HTTP CONNECT response")
    try:
        status_code = int(parts[1])
    except ValueError as exc:
        sock.close()
        raise ImapConnectionError("Proxy returned an invalid HTTP CONNECT status") from exc
    if status_code != 200:
        sock.close()
        reason = parts[2].strip() if len(parts) > 2 else "CONNECT failed"
        if status_code == 407:
            raise ImapConnectionError("HTTP proxy authentication failed while connecting to Gmail IMAP")
        if status_code in (400, 403, 405):
            raise ImapConnectionError(
                "HTTP proxy rejected CONNECT to imap.gmail.com:993 (%s %s). Use a proxy that allows TCP CONNECT to port 993, or switch this proxy to SOCKS5 if it is a SOCKS endpoint."
                % (status_code, reason)
            )
        raise ImapConnectionError("HTTP proxy CONNECT to Gmail IMAP failed: %s %s" % (status_code, reason))
    return sock


def _create_socks5_tunnel(proxy: ProxyConfig, host: str, port: int, timeout: int) -> socket.socket:
    password = decrypt_secret(proxy.encrypted_password)
    return socks.create_connection(
        (host, port),
        timeout=timeout,
        proxy_type=socks.SOCKS5,
        proxy_addr=proxy.host,
        proxy_port=proxy.port,
        proxy_rdns=True,
        proxy_username=proxy.username,
        proxy_password=password,
    )


def _proxy_tls_error_message(proxy: ProxyConfig, message: str) -> str:
    if "UNEXPECTED_EOF_WHILE_READING" not in message:
        return message
    proxy_hint = "SOCKS5" if proxy.type == "socks5" else "HTTP CONNECT"
    return (
        "TLS handshake to Gmail IMAP ended early through the proxy. "
        "The proxy accepted the %s connection but closed or blocked the tunnel before Gmail completed TLS. "
        "Use a proxy that allows raw TCP/TLS traffic to imap.gmail.com:993, or switch to a verified SOCKS5 proxy. "
        "Original error: %s" % (proxy_hint, message)
    )


def diagnose_imap_proxy(proxy: Optional[ProxyConfig]) -> Dict[str, object]:
    start = time.time()
    target = "%s:%s" % (IMAP_HOST, IMAP_PORT)
    timeout = proxy.timeout_seconds if proxy else 30
    sock = None
    tls_sock = None
    stage = "tcp"
    try:
        if proxy:
            stage = "proxy_connect" if proxy.type == "http" else "socks5_connect"
            if proxy.type == "http":
                sock = _create_http_tunnel(proxy, IMAP_HOST, IMAP_PORT, timeout)
            else:
                sock = _create_socks5_tunnel(proxy, IMAP_HOST, IMAP_PORT, timeout)
        else:
            sock = socket.create_connection((IMAP_HOST, IMAP_PORT), timeout=timeout)
        stage = "tls"
        tls_sock = ssl.create_default_context().wrap_socket(sock, server_hostname=IMAP_HOST)
        sock = None
        stage = "imap_greeting"
        detail = "TLS handshake completed"
        try:
            tls_sock.settimeout(min(timeout, 5))
            greeting = tls_sock.recv(512).decode("utf-8", errors="replace").strip()
            if greeting:
                detail = greeting[:240]
        except socket.timeout:
            detail = "TLS handshake completed; IMAP greeting read timed out"
        return {
            "ok": True,
            "target": target,
            "stage": stage,
            "detail": detail,
            "elapsed_ms": int((time.time() - start) * 1000),
        }
    except ssl.SSLError as exc:
        error = str(exc)
        if proxy:
            error = _proxy_tls_error_message(proxy, error)
        return {
            "ok": False,
            "target": target,
            "stage": stage,
            "error": error,
            "elapsed_ms": int((time.time() - start) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "target": target,
            "stage": stage,
            "error": str(exc),
            "elapsed_ms": int((time.time() - start) * 1000),
        }
    finally:
        for handle in (tls_sock, sock):
            if handle:
                try:
                    handle.close()
                except Exception:
                    pass


class ProxiedIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, host: str, port: int, proxy: Optional[ProxyConfig], timeout: int):
        self._mail_proxy = proxy
        self._mail_timeout = timeout
        super().__init__(host=host, port=port, ssl_context=ssl.create_default_context(), timeout=timeout)

    def _create_socket(self, timeout):
        timeout = timeout or self._mail_timeout
        if self._mail_proxy:
            if self._mail_proxy.type == "http":
                sock = _create_http_tunnel(self._mail_proxy, self.host, self.port, timeout)
            else:
                sock = _create_socks5_tunnel(self._mail_proxy, self.host, self.port, timeout)
        else:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def connect_imap(email: str, app_password: str, proxy: Optional[ProxyConfig] = None):
    timeout = proxy.timeout_seconds if proxy else 30
    last_error = ""
    for attempt in range(1, IMAP_CONNECT_ATTEMPTS + 1):
        try:
            client = ProxiedIMAP4SSL(IMAP_HOST, IMAP_PORT, proxy, timeout)
            client.login(email, normalize_app_password(app_password))
            return client
        except imaplib.IMAP4.error as exc:
            raise ImapAuthError(str(exc))
        except ssl.SSLError as exc:
            message = str(exc)
            if proxy:
                message = _proxy_tls_error_message(proxy, message)
            last_error = message
        except Exception as exc:
            last_error = str(exc)

        if attempt < IMAP_CONNECT_ATTEMPTS and _is_transient_connection_error(last_error):
            time.sleep(0.6 * attempt)
            continue
        break

    if proxy and proxy.type == "socks5" and "TLS handshake to Gmail IMAP ended early" in last_error:
        last_error += (
            " Retried %s time(s). For local SOCKS5 proxies such as 127.0.0.1:7890, "
            "make sure your proxy client routes imap.gmail.com:993 through a node that allows raw TCP/TLS IMAP traffic; "
            "some rules or nodes only allow web HTTPS traffic."
            % IMAP_CONNECT_ATTEMPTS
        )
    raise ImapConnectionError(last_error)


def test_imap_login(email: str, app_password: str, proxy: Optional[ProxyConfig] = None) -> Dict[str, str]:
    client = connect_imap(email, app_password, proxy)
    try:
        typ, data = client.select("INBOX", readonly=True)
        if typ != "OK":
            raise ImapConnectionError("unable to select INBOX")
        count = data[0].decode("utf-8", errors="replace") if data else "0"
        return {"email": email, "inbox_count": count}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _decode_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _addresses(values: List[str]) -> List[str]:
    return [addr for _, addr in getaddresses(values) if addr]


def _date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _headers(message) -> Dict[str, str]:
    raw: Dict[str, str] = {}
    for key, value in message.items():
        decoded = _decode_text(value) or ""
        lower = key.lower()
        raw[lower] = (raw[lower] + ", " + decoded) if lower in raw else decoded
    return raw


def _safe_filename(value: str) -> str:
    value = value.replace("\\", "_").replace("/", "_").strip()
    return value or "attachment.bin"


def parse_imap_message(uid: str, raw_bytes: bytes) -> Dict:
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    headers = _headers(message)
    texts: List[str] = []
    htmls: List[str] = []
    attachments: List[Dict] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        content_disposition = part.get_content_disposition()
        filename = part.get_filename()
        decoded_filename = _decode_text(filename) if filename else None
        payload = part.get_payload(decode=True) or b""
        content_type = part.get_content_type()
        if decoded_filename or content_disposition == "attachment":
            attachment_index = len(attachments) + 1
            attachments.append(
                {
                    "gmail_attachment_id": "%s:%s" % (uid, attachment_index),
                    "part_id": str(attachment_index),
                    "filename": _safe_filename(decoded_filename or "attachment-%s" % attachment_index),
                    "mime_type": content_type,
                    "size": len(payload),
                    "data": payload,
                }
            )
            continue
        if content_type == "text/plain":
            try:
                texts.append(part.get_content())
            except Exception:
                texts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        elif content_type == "text/html":
            try:
                htmls.append(part.get_content())
            except Exception:
                htmls.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))

    recipients = _addresses(message.get_all("to", []) or [])
    cc = _addresses(message.get_all("cc", []) or [])
    return {
        "gmail_message_id": str(uid),
        "thread_id": None,
        "history_id": str(uid),
        "rfc_message_id": headers.get("message-id"),
        "subject": headers.get("subject"),
        "sender": headers.get("from"),
        "recipients": recipients,
        "cc": cc,
        "received_at": _date(headers.get("date")),
        "internal_date_ms": None,
        "snippet": (texts[0] if texts else "").strip()[:240] or None,
        "text_body": "\n".join([text for text in texts if text]).strip() or None,
        "html_body": "\n".join([html for html in htmls if html]).strip() or None,
        "raw_headers": dict(message.items()),
        "lower_headers": headers,
        "attachments": attachments,
        "has_attachment": bool(attachments),
    }


def fetch_uids(client, last_uid: Optional[str], days: int, limit: int) -> List[str]:
    typ, _ = client.select("INBOX", readonly=True)
    if typ != "OK":
        raise ImapConnectionError("unable to select INBOX")
    if last_uid and str(last_uid).isdigit():
        criteria = ["UID", "%s:*" % (int(last_uid) + 1)]
    else:
        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%b-%Y")
        criteria = ["SINCE", since]
    typ, data = client.uid("search", None, *criteria)
    if typ != "OK":
        raise ImapConnectionError("IMAP search failed")
    raw_uids = data[0].decode("ascii", errors="ignore").split() if data and data[0] else []
    uids = sorted({int(uid) for uid in raw_uids if uid.isdigit()})
    return [str(uid) for uid in uids[-limit:]]


def fetch_message_raw(client, uid: str) -> bytes:
    typ, data = client.uid("fetch", uid, "(RFC822)")
    if typ != "OK":
        raise ImapConnectionError("IMAP fetch failed for UID %s" % uid)
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    raise ImapConnectionError("IMAP fetch returned no RFC822 payload for UID %s" % uid)


def attachment_storage_path(account_id: int, message_uid: str, filename: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:16]
    base_dir = os.path.abspath(os.path.join(os.path.dirname(settings.database_url.replace("sqlite:///", "")), "attachments"))
    if not settings.database_url.startswith("sqlite:///"):
        base_dir = os.path.abspath(os.path.join("data", "attachments"))
    target_dir = os.path.join(base_dir, str(account_id))
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, "%s-%s-%s" % (message_uid, digest, _safe_filename(filename)))


def read_attachment_payload(path: Optional[str]) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as handle:
        return base64.urlsafe_b64encode(handle.read()).decode("ascii").rstrip("=")
