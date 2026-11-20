from datetime import datetime, timezone

from aether_agentic import capture_request_evidence, capture_request_evidence_from_wsgi

RECEIVED = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def test_captures_request_metadata_and_signature_headers():
    ev = capture_request_evidence(
        method="get",
        url="/products/1?ref=x",
        headers={
            "Host": "shop.example",
            "User-Agent": "ChatGPT-User/1.0",
            "Signature": "sig1=:AAAA:",
            "Signature-Input": 'sig1=("@authority");tag="web-bot-auth"',
            "Signature-Agent": '"https://chatgpt.com"',
            "Cookie": "session=secret",
            "Authorization": "Bearer secret",
        },
        client_ip="::ffff:203.0.113.7",
        received_at=RECEIVED,
    )
    assert ev == {
        "receivedAt": "2026-11-19T12:00:00Z",
        "userAgent": "ChatGPT-User/1.0",
        "clientIp": "203.0.113.7",
        "method": "GET",
        "authority": "shop.example",
        "path": "/products/1",
        "query": "ref=x",
        "scheme": "https",
        "signature": "sig1=:AAAA:",
        "signatureInput": 'sig1=("@authority");tag="web-bot-auth"',
        "signatureAgent": '"https://chatgpt.com"',
    }


def test_forwarded_for_is_ignored_unless_trusted():
    headers = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
    assert "clientIp" not in capture_request_evidence(method="GET", url="/", headers=headers)
    trusted = capture_request_evidence(method="GET", url="/", headers=headers, trust_forwarded_for=True)
    assert trusted["clientIp"] == "1.2.3.4"


def test_wsgi_environ():
    ev = capture_request_evidence_from_wsgi({
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/api/x",
        "QUERY_STRING": "a=1",
        "wsgi.url_scheme": "https",
        "HTTP_HOST": "shop.example",
        "HTTP_USER_AGENT": "GPTBot/1.2",
        "HTTP_COOKIE": "c=1",
        "REMOTE_ADDR": "198.51.100.9",
    })
    assert ev["authority"] == "shop.example"
    assert ev["path"] == "/api/x" and ev["query"] == "a=1"
    assert ev["clientIp"] == "198.51.100.9"
    assert ev["userAgent"] == "GPTBot/1.2"
    assert "c=1" not in str(ev)
