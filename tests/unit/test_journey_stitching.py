import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "Backend Architecture" / "aether-backend" / "services" / "journeys" / "stitching.py"


def load_module():
    spec = importlib.util.spec_from_file_location("journey_stitching", MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_fingerprint_alone_never_high_confidence():
    mod = load_module()
    svc = mod.JourneyStitchingService()
    score, signals = svc.score(fingerprint="fp_1", timestamp_proximity=False)
    assert "fingerprint_match" in signals
    assert score < 0.5


def test_tenant_scoped_handoff_stitching():
    mod = load_module()
    svc = mod.JourneyStitchingService()
    first = {
        "id": "evt1", "type": "journey_started", "timestamp": "2026-06-04T00:00:00Z",
        "sessionId": "s1", "anonymousId": "anon1", "userId": "u1",
        "properties": {"journeyType": "checkout"},
        "context": {"library": {"name": "@aether/web", "version": "1"}, "device": {"type": "desktop"}},
    }
    second = {
        "id": "evt2", "type": "journey_resumed", "timestamp": "2026-06-04T00:20:00Z",
        "sessionId": "s2", "anonymousId": "anon2", "userId": "u1",
        "properties": {"confidence": 0.97, "confidenceSignals": ["user_id_match", "email_hash_match"]},
        "context": {"library": {"name": "@aether/ios", "version": "1"}, "device": {"type": "mobile"}},
    }
    j1 = svc.ingest_event("tenant-a", first)
    j2 = svc.ingest_event("tenant-a", second)
    assert j1 is not None and j2 is not None
    assert j1.journey_id == j2.journey_id
    assert len(j2.handoffs) == 1
    assert svc.list_for_user("tenant-b", "u1") == []
