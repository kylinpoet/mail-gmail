import base64

from app.services.gmail import parse_message


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def test_parse_message_extracts_headers_bodies_and_attachment():
    payload = {
        "id": "msg-1",
        "threadId": "thread-1",
        "historyId": "42",
        "internalDate": "1700000000000",
        "snippet": "hello",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "user+shop-1@gmail.com"},
                {"name": "Message-ID", "value": "<m1@example.com>"},
            ],
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("plain body")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
                {
                    "filename": "invoice.pdf",
                    "mimeType": "application/pdf",
                    "partId": "2",
                    "body": {"attachmentId": "att-1", "size": 10},
                },
            ],
        },
    }

    parsed = parse_message(payload)

    assert parsed["gmail_message_id"] == "msg-1"
    assert parsed["subject"] == "Hello"
    assert parsed["text_body"] == "plain body"
    assert parsed["html_body"] == "<p>html</p>"
    assert parsed["has_attachment"] is True
    assert parsed["attachments"][0]["filename"] == "invoice.pdf"

