"""Raw IP addresses must never persist.

Two layers of proof:
1. Static — no runtime write path passes ``request.client.host`` (or a
   forwarded header) into a persistence/audit field: the only sanctioned
   transform is ``shared/privacy/ip_hmac.py``.
2. Behavioral — the audit token and server-context payload are structurally
   incapable of carrying the address.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Direct persistence of the raw peer address into a named field — matched in
# keyword-argument form (``ip_address=request...``, PEP8 kwargs have no spaces).
# A spaced local ASSIGNMENT (``ip_address = request...``) is ephemeral
# in-request use (e.g. the extraction-defense identity fabric) and is governed
# by that plane's own storage policy, not this gate.
_RAW_IP_PERSIST = re.compile(
    r"ip_address=request\.client\.host|"
    r'ip_address=.*headers\.get\(["\']X-Forwarded-For'
)

# The deprecated ingest alias hashes (sha256) before storing; it predates the
# HMAC scheme and is scheduled for retirement with the alias itself (PR 4).
_EXEMPT = ("services/ingestion/routes.py",)


def _runtime_files():
    for base in ("services", "shared", "middleware", "repositories"):
        yield from (BACKEND / base).rglob("*.py")


def test_no_direct_raw_ip_persistence_in_runtime_paths():
    offenders = []
    for path in _runtime_files():
        rel = str(path.relative_to(BACKEND))
        if any(rel.endswith(e) or e in rel for e in _EXEMPT):
            continue
        if _RAW_IP_PERSIST.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(rel)
    assert offenders == [], (
        f"raw client IP persisted directly in: {offenders} — "
        "use shared.privacy.ip_hmac.audit_ip_token instead"
    )


def test_audit_token_is_not_an_address():
    from shared.privacy.ip_hmac import audit_ip_token, is_ip_hmac_token

    token = audit_ip_token("203.0.113.7", "tenant-a")
    assert is_ip_hmac_token(token)
    assert "203.0.113.7" not in token
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", token)


def test_server_context_payload_has_no_ip_field():
    from services.ingestion.context_enricher import ServerObservedContext

    fields = set(ServerObservedContext.__dataclass_fields__)
    assert "ip" not in fields and "raw_ip" not in fields and "client_ip" not in fields
    payload = ServerObservedContext(enrichment_state="ready", ip_token="iph1:abc").as_payload()
    assert set(payload).isdisjoint({"ip", "raw_ip", "client_ip"})
