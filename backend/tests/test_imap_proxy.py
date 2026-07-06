import socket
import ssl
import threading

from app.models import ProxyConfig
from app.services import imap_mail
from app.services.imap_mail import _create_http_tunnel, connect_imap


def test_http_proxy_tunnel_consumes_connect_headers():
    ready = threading.Event()
    received = []

    def run_proxy(server):
        server.listen(1)
        ready.set()
        conn, _ = server.accept()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            received.append(data)
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: test\r\n\r\n")
            assert conn.recv(4) == b"ping"
            conn.sendall(b"pong")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        host, port = server.getsockname()
        thread = threading.Thread(target=run_proxy, args=(server,), daemon=True)
        thread.start()
        ready.wait(2)

        proxy = ProxyConfig(type="http", host=host, port=port, timeout_seconds=2)
        sock = _create_http_tunnel(proxy, "imap.gmail.com", 993, 2)
        try:
            assert b"CONNECT imap.gmail.com:993 HTTP/1.1" in received[0]
            sock.sendall(b"ping")
            assert sock.recv(4) == b"pong"
        finally:
            sock.close()


def test_connect_imap_retries_transient_tls_eof(monkeypatch):
    attempts = {"count": 0}

    class DummyClient:
        def login(self, email, password):
            return "OK", []

    def fake_imap_client(host, port, proxy, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
        return DummyClient()

    monkeypatch.setattr(imap_mail, "ProxiedIMAP4SSL", fake_imap_client)
    monkeypatch.setattr(imap_mail.time, "sleep", lambda seconds: None)

    client = connect_imap("user@gmail.com", "app-password", ProxyConfig(type="socks5", host="127.0.0.1", port=7890))

    assert isinstance(client, DummyClient)
    assert attempts["count"] == 2
