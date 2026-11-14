#!/usr/bin/env python3
"""Generate the shared SDK manifest-signing test vectors.

Writes tests/fixtures/sdk/manifest-signing-vectors.json, which the backend, web,
iOS and Android test suites all verify against (see
docs/reference/sdks/manifest-signing.md). ECDSA signatures are randomized, so run
this only when the spec changes and commit the result; ``--check`` re-verifies the
committed file without rewriting it.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from ingestion.sdk_config import manifest_signing as ms  # noqa: E402

VECTORS = ROOT / "tests" / "fixtures" / "sdk" / "manifest-signing-vectors.json"
TEST_SECRET = "aether-sdk-manifest-test-vector-secret"

# (name, JSON text). The expected canonical form is computed by the reference.
CANONICAL_INPUTS = [
    ("empty_object", "{}"),
    ("empty_array", "[]"),
    ("scalars", '{"t":true,"f":false,"n":null,"i":0,"neg":-7,"big":9007199254740991}'),
    ("key_order", '{"b":1,"a":2,"B":3,"_":4,"1":5}'),
    ("nested", '{"z":{"y":[3,{"x":1,"w":[]}],"a":{}},"a":[[],[[]]]}'),
    ("whitespace_is_insignificant", ' { "a" : [ 1 , 2 ] , "b" : { } } '),
    ("string_escapes", '{"s":"quote\\" backslash\\\\ slash/ tab\\t nl\\n cr\\r bs\\b ff\\f"}'),
    ("control_chars", '{"s":"\\u0000\\u0001\\u001f\\u007f"}'),
    ("unicode_literal", '{"s":"é 日本語 \\u00e9 \\u65e5"}'),
    ("astral_plane", '{"s":"\\ud83d\\ude00 and 😀"}'),
    ("line_separators", '{"s":"\\u2028\\u2029"}'),
]

# JSON texts that MUST be rejected by every implementation.
REJECTED_INPUTS = [
    ("fractional_number", '{"ratio":0.5}'),
    ("negative_fractional_number", '{"ratio":-0.25}'),
    ("non_ascii_key", '{"é":1}'),
    ("integer_beyond_safe_range", '{"n":9007199254740993}'),
]


def _manifest(**overrides: object) -> dict:
    body = {
        "manifest_version": "42",
        "min_sdk_version": "0.1.0-alpha.0",
        "schema_version": "7.0.0",
        "rollout_percentage": 100,
        "features": {"analytics": True, "web3": False, "session_replay": True},
        "endpoints": {"events": "https://ingest.example.test/v1/batch", "config": "https://api.example.test"},
        "flags": {"heartbeat_interval_seconds": 60, "banner": "Héllo 😀", "nested": {"on": True, "ids": [1, 2, 3]}},
        "published_at": "2026-10-23T03:00:00+00:00",
        "source": "tenant_published",
        "publisher_id": "system",
        "signature_alg": ms.SIGNATURE_ALG,
        "signature": "",
    }
    body.update(overrides)
    return body


def build() -> dict:
    key = ms.derive_private_key(TEST_SECRET)
    other = ms.derive_private_key(TEST_SECRET + "-other")

    canonical = [
        {"name": n, "input_json": text, "canonical": ms.canonical_json(json.loads(text))}
        for n, text in CANONICAL_INPUTS
    ]
    rejected = [{"name": n, "input_json": text} for n, text in REJECTED_INPUTS]

    good = _manifest()
    good["signature"] = ms.sign(key, good)
    min_good = _manifest(features={}, endpoints={}, flags={})
    min_good["signature"] = ms.sign(key, min_good)

    def case(name: str, manifest: dict, valid: bool, why: str) -> dict:
        return {"name": name, "valid": valid, "why": why, "manifest_json": json.dumps(manifest, ensure_ascii=False)}

    cases = [
        case("valid_full_manifest", good, True, "signed over every field"),
        case("valid_empty_collections", min_good, True, "empty features/endpoints/flags"),
    ]

    def tampered(name: str, why: str, **changes: object) -> dict:
        m = copy.deepcopy(good)
        m.update(changes)
        return case(name, m, False, why)

    cases += [
        tampered("tampered_rollout", "rollout_percentage changed after signing", rollout_percentage=5),
        tampered("tampered_feature", "a feature flipped after signing", features={"analytics": False, "web3": False, "session_replay": True}),
        tampered("tampered_endpoint", "endpoint redirected after signing", endpoints={"events": "https://evil.example.test", "config": "https://api.example.test"}),
        tampered("tampered_flag_value", "nested flag value changed", flags={"heartbeat_interval_seconds": 61, "banner": "Héllo 😀", "nested": {"on": True, "ids": [1, 2, 3]}}),
        tampered("tampered_manifest_version", "version changed (replay of an older/newer manifest)", manifest_version="43"),
        tampered("downgraded_alg", "signature_alg rewritten", signature_alg="none"),
        tampered("unknown_alg", "unsupported algorithm identifier", signature_alg="hmac-sha256"),
        tampered("empty_signature", "signature stripped", signature=""),
        tampered("short_signature", "signature is not 64 bytes", signature=ms.b64url_encode(b"\x01" * 63)),
        tampered("zero_signature", "all-zero r||s", signature=ms.b64url_encode(b"\x00" * 64)),
        tampered("padded_signature", "base64url must be unpadded", signature=good["signature"] + "=="),
    ]
    extra = copy.deepcopy(good)
    extra["injected"] = "added after signing"
    cases.append(case("extra_unsigned_field", extra, False, "every field is signed, so an added field breaks the signature"))
    missing_alg = copy.deepcopy(good)
    del missing_alg["signature_alg"]
    cases.append(case("missing_alg", missing_alg, False, "signature_alg is required"))
    no_sig = copy.deepcopy(good)
    del no_sig["signature"]
    cases.append(case("missing_signature", no_sig, False, "signature is required"))
    wrong_key = _manifest()
    wrong_key["signature"] = ms.sign(other, wrong_key)
    cases.append(case("signed_by_other_key", wrong_key, False, "valid signature from a different key"))

    return {
        "spec": "docs/reference/sdks/manifest-signing.md",
        "alg": ms.SIGNATURE_ALG,
        "test_secret": TEST_SECRET,
        "public_key_spki_b64url": ms.public_key_spki_b64url(key),
        "other_public_key_spki_b64url": ms.public_key_spki_b64url(other),
        "canonical": canonical,
        "rejected_inputs": rejected,
        "manifests": cases,
    }


def check() -> list[str]:
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    problems: list[str] = []
    if data["public_key_spki_b64url"] != ms.public_key_spki_b64url(ms.derive_private_key(data["test_secret"])):
        problems.append("public key does not match the derivation from test_secret")
    for c in data["canonical"]:
        if ms.canonical_json(json.loads(c["input_json"])) != c["canonical"]:
            problems.append(f"canonical drift: {c['name']}")
    for r in data["rejected_inputs"]:
        try:
            ms.canonical_json(json.loads(r["input_json"]))
            problems.append(f"expected rejection: {r['name']}")
        except ms.ManifestSigningError:
            pass
    for m in data["manifests"]:
        got = ms.verify(data["public_key_spki_b64url"], json.loads(m["manifest_json"]))
        if got != m["valid"]:
            problems.append(f"verify mismatch: {m['name']} (expected {m['valid']})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the committed vectors; do not rewrite")
    args = parser.parse_args()
    if not args.check:
        VECTORS.parent.mkdir(parents=True, exist_ok=True)
        VECTORS.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {VECTORS.relative_to(ROOT)}")
    problems = check()
    if problems:
        print("SDK manifest vectors FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("SDK manifest vectors OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
