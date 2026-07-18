"""Credentialless certification checks.

Every check runs WITHOUT network access or real credentials. A check that cannot
apply — because the adapter does not declare or expose the relevant capability —
SKIPS rather than fails. That is the whole point: certification asserts on the
*honest declaration* the adapter makes (its descriptor) plus any offline hooks it
chooses to expose, never on a live call.

The design mirrors ``services/derivatives/adapters/conformance.py`` (mechanical
invariant checks over an adapter), generalized so any domain adapter — payments,
interop, derivatives, stablecoin-chain — can be certified through one interface.

Adapters participate by exposing a ``certification_descriptor()`` returning an
``AdapterCertificationDescriptor``. Behavioral checks additionally probe OPTIONAL
duck-typed hooks (``sanitize_payload``, ``build_request``, ``normalize``,
``verify_webhook``, ``dedupe_key``, ``sequence_of``, ``health``); when a hook is
absent the corresponding check skips.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:  # avoid an import cycle with descriptor.py at runtime
    from shared.certification.descriptor import AdapterCertificationDescriptor

# Import readiness token for honest-status reasoning (no cycle: readiness has no
# dependency on this module).
from shared.certification.readiness import CredentialReadiness

# Sentinels meaning "not declared" for free-text descriptor fields.
_UNDECLARED = {"", "none", "unspecified", "unknown", "n/a", None}
_KNOWN_PAGINATION = {"none", "cursor", "page", "time_window", "offset"}
_KNOWN_STREAMING = {"none", "websocket", "sse", "webhook", "polling"}

# Payload used to prove a sanitizer redacts secret-like material.
_SECRET_PAYLOAD: dict[str, Any] = {
    "authorization": "Bearer sk_live_TOPSECRET",
    "api_key": "sk_live_TOPSECRET",
    "safe_field": "keep-me",
    "amount": "10.00",
    "nested": {"password": "hunter2", "token": "tok_secret", "note": "ok"},
    "headers": {"Authorization": "Bearer sk_live_TOPSECRET"},
}
_SECRET_MARKERS = ("TOPSECRET", "hunter2", "tok_secret")


class CertificationCheckResult(BaseModel):
    """Outcome of a single certification check.

    ``skipped`` marks an inapplicable check (capability not declared/exposed);
    a skipped check is not a failure. ``passed`` is ``True`` for skips so that
    "all passed" reasoning treats skips as non-blocking.
    """

    name: str
    passed: bool
    skipped: bool = False
    detail: str = ""


@runtime_checkable
class CertifiableAdapter(Protocol):
    """Minimal duck interface a domain adapter exposes for certification.

    Only ``certification_descriptor`` is required. The remaining hooks are
    OPTIONAL — adapters that only publish a descriptor still certify on the
    descriptor-level checks; behavioral checks skip when their hook is absent.

    Optional hooks (checked via ``getattr``, not part of the required Protocol):
        sanitize_payload(payload) -> sanitized | (sanitized, stripped_keys)
        build_request(ctx) -> mapping-like request (url/headers/params)
        normalize(payload) -> canonical record(s)
        verify_webhook(...) -> bool
        dedupe_key(event) -> hashable
        sequence_of(event) -> comparable
        health(context) -> mapping with a state
    """

    def certification_descriptor(self) -> "AdapterCertificationDescriptor": ...


# ── helpers ────────────────────────────────────────────────────────────────


def _descriptor(adapter: Any) -> "AdapterCertificationDescriptor":
    """Resolve the certification descriptor from an adapter or accept a
    descriptor passed directly."""
    hook = getattr(adapter, "certification_descriptor", None)
    if callable(hook):
        return hook()
    # An AdapterCertificationDescriptor exposes ``implementation_state``; accept
    # it directly so callers can certify a bare descriptor.
    if hasattr(adapter, "implementation_state"):
        return adapter  # type: ignore[return-value]
    raise TypeError(
        "adapter exposes neither certification_descriptor() nor a descriptor shape"
    )


def _hook(adapter: Any, name: str):
    fn = getattr(adapter, name, None)
    return fn if callable(fn) else None


def _declared(value: Any) -> bool:
    return str(value).strip().lower() not in _UNDECLARED


def _flatten_strings(value: Any) -> list[str]:
    """Collect all string values (keys and values) from a nested structure."""
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out.append(str(k))
            out.extend(_flatten_strings(v))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            out.extend(_flatten_strings(item))
    else:
        out.append(str(value))
    return out


def _unwrap_sanitizer(result: Any) -> Any:
    """Payment-style sanitizers return ``(sanitized, stripped_keys)``; others
    return the sanitized value directly. Normalize to the sanitized value."""
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[1], (list, tuple))
    ):
        return result[0]
    return result


def _ok(name: str, detail: str = "") -> CertificationCheckResult:
    return CertificationCheckResult(name=name, passed=True, detail=detail)


def _fail(name: str, detail: str) -> CertificationCheckResult:
    return CertificationCheckResult(name=name, passed=False, detail=detail)


def _skip(name: str, detail: str) -> CertificationCheckResult:
    return CertificationCheckResult(name=name, passed=True, skipped=True, detail=detail)


# ── descriptor-declaration checks ────────────────────────────────────────────


def check_descriptor_completeness(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "descriptor_completeness"
    d = _descriptor(adapter)
    required = {
        "provider": d.provider,
        "domain": d.domain,
        "adapter": d.adapter,
        "adapter_version": d.adapter_version,
        "implementation_state": d.implementation_state,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        return _fail(name, f"missing/empty descriptor fields: {sorted(missing)}")
    return _ok(name, f"{d.provider}/{d.domain}: core descriptor fields present")


def check_honest_status(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """A descriptor may not claim more than its evidence supports.

    PARTNER_LIVE / SANDBOX_VALIDATED require live evidence (``ctx['live_evidence']``
    or a ``last_certified_at`` stamp). REPLAY_VALIDATED requires either a
    fixture schema version or replay evidence.
    """
    name = "honest_status"
    d = _descriptor(adapter)
    state = d.implementation_state
    has_live = bool(ctx.get("live_evidence")) or bool(d.last_certified_at)
    if state in (CredentialReadiness.PARTNER_LIVE, CredentialReadiness.SANDBOX_VALIDATED):
        if not has_live:
            return _fail(
                name,
                f"state {state.value!r} claimed with no live evidence "
                "(no ctx['live_evidence'] and no last_certified_at)",
            )
    if state == CredentialReadiness.REPLAY_VALIDATED:
        if not (bool(ctx.get("replay_evidence")) or _declared(d.fixture_schema_version)):
            return _fail(
                name,
                "replay_validated claimed with no fixture_schema_version or "
                "ctx['replay_evidence']",
            )
    return _ok(name, f"state {state.value!r} is consistent with declared evidence")


def check_unsupported_marked(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "unsupported_marked"
    d = _descriptor(adapter)
    supported = set(d.supported_operations)
    unsupported = set(d.unsupported_operations)
    if not supported and not unsupported:
        return _skip(name, "no operations declared")
    overlap = supported & unsupported
    if overlap:
        return _fail(name, f"operations both supported and unsupported: {sorted(overlap)}")
    return _ok(
        name,
        f"{len(supported)} supported / {len(unsupported)} unsupported, disjoint",
    )


def check_timeout_declared(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "timeout_declared"
    timeout = ctx.get("timeout_seconds")
    if timeout is None:
        return _skip(name, "no timeout declared in ctx['timeout_seconds']")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return _fail(name, f"declared timeout is not a positive number: {timeout!r}")
    return _ok(name, f"timeout declared: {timeout}s")


def check_retry_declared(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "retry_declared"
    d = _descriptor(adapter)
    if not _declared(d.retry_policy):
        return _skip(name, "retry_policy not declared")
    return _ok(name, f"retry_policy declared: {d.retry_policy!r}")


def check_rate_limit_declared(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "rate_limit_declared"
    d = _descriptor(adapter)
    if not _declared(d.rate_limit_behavior):
        return _skip(name, "rate_limit_behavior not declared")
    return _ok(name, f"rate_limit_behavior declared: {d.rate_limit_behavior!r}")


def check_pagination(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "pagination"
    d = _descriptor(adapter)
    model = str(d.pagination_model).strip().lower()
    if model == "none":
        return _skip(name, "pagination_model == 'none'")
    if model not in _KNOWN_PAGINATION:
        return _fail(name, f"unknown pagination_model: {d.pagination_model!r}")
    return _ok(name, f"pagination_model declared: {model!r}")


def check_cursor_persistence(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """Cursor-paginated adapters must persist a cursor across pulls. Without a
    cursor model there is nothing to persist → skip."""
    name = "cursor_persistence"
    d = _descriptor(adapter)
    if str(d.pagination_model).strip().lower() != "cursor":
        return _skip(name, "no cursor pagination model")
    checkpoint = _hook(adapter, "advance_cursor") or _hook(adapter, "next_cursor")
    if checkpoint is None and "cursor" not in ctx:
        return _ok(name, "cursor pagination declared (advance hook not exposed)")
    cursor = ctx.get("cursor", "cur_0")
    if checkpoint is not None:
        try:
            nxt = checkpoint(cursor)
        except Exception as exc:  # pragma: no cover - adapter bug surface
            return _fail(name, f"advance_cursor raised: {exc}")
        if nxt == cursor:
            return _fail(name, "advance_cursor did not move the cursor forward")
        return _ok(name, "cursor advanced across a pull")
    return _ok(name, "cursor pagination declared")


# ── behavioral checks (skip when the hook is not exposed) ─────────────────────


def check_secret_redaction(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """Feed a payload containing secret-like keys / Authorization headers and
    assert the adapter's sanitizer removes or redacts them. Skips when the
    adapter exposes no sanitizer."""
    name = "secret_redaction"
    sanitize = _hook(adapter, "sanitize_payload")
    if sanitize is None:
        return _skip(name, "no sanitize_payload hook")
    payload = ctx.get("secret_payload", _SECRET_PAYLOAD)
    try:
        sanitized = _unwrap_sanitizer(sanitize(payload))
    except Exception as exc:  # pragma: no cover - adapter bug surface
        return _fail(name, f"sanitize_payload raised: {exc}")
    leaked = [
        marker
        for value in _flatten_strings(sanitized)
        for marker in _SECRET_MARKERS
        if marker in value
    ]
    if leaked:
        return _fail(name, f"secret material survived sanitization: {sorted(set(leaked))}")
    return _ok(name, "secret-like keys/values redacted")


def check_request_construction(adapter: Any, ctx: dict) -> CertificationCheckResult:
    name = "request_construction"
    build = _hook(adapter, "build_request")
    if build is None:
        return _skip(name, "no build_request hook")
    request_ctx = ctx.get("sample_request", {})
    try:
        request = build(request_ctx)
    except Exception as exc:
        return _fail(name, f"build_request raised: {exc}")
    if not isinstance(request, dict) or not request:
        return _fail(name, f"build_request returned a non-mapping/empty value: {request!r}")
    if not (request.get("url") or request.get("endpoint") or request.get("path")):
        return _fail(name, "constructed request declares no url/endpoint/path")
    return _ok(name, "request constructed with a target endpoint")


def check_auth_injection(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """When credentials are required and a request builder exists, a fake secret
    passed via ctx must be injected into the request (headers/params), proving an
    auth-injection seam. Skips when no builder or no declared credentials."""
    name = "auth_injection"
    build = _hook(adapter, "build_request")
    d = _descriptor(adapter)
    if build is None:
        return _skip(name, "no build_request hook")
    if not d.required_credentials and not d.secret_ref_names:
        return _skip(name, "adapter declares no credentials/secret refs")
    marker = "FAKE_INJECTED_SECRET"
    request_ctx = dict(ctx.get("sample_request", {}))
    request_ctx["credential"] = {"api_key": marker, "secret": marker}
    try:
        request = build(request_ctx)
    except Exception as exc:
        return _fail(name, f"build_request raised with a credential: {exc}")
    seen = marker in "".join(_flatten_strings(request))
    if not seen:
        return _fail(name, "credential was not injected into the constructed request")
    return _ok(name, "credential injected into request auth")


def check_duplicate_handling(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """Two identical events must yield the same dedupe key; two distinct events
    must differ. Skips when no dedupe_key hook is exposed."""
    name = "duplicate_handling"
    dedupe = _hook(adapter, "dedupe_key")
    if dedupe is None:
        return _skip(name, "no dedupe_key hook")
    events = ctx.get("events")
    if not events or len(events) < 2:
        events = [
            {"id": "evt_1", "seq": 1, "value": "a"},
            {"id": "evt_1", "seq": 1, "value": "a"},
            {"id": "evt_2", "seq": 2, "value": "b"},
        ]
    try:
        k0, k1 = dedupe(events[0]), dedupe(events[1])
    except Exception as exc:
        return _fail(name, f"dedupe_key raised: {exc}")
    if k0 != k1:
        return _fail(name, "identical events produced different dedupe keys")
    if len(events) > 2:
        if dedupe(events[2]) == k0:
            return _fail(name, "distinct events collided on the same dedupe key")
    return _ok(name, "dedupe key stable for duplicates, distinct for others")


def check_out_of_order_handling(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """A sequence hook must impose a total order so out-of-order arrivals sort
    deterministically. Skips when no sequence_of hook is exposed."""
    name = "out_of_order_handling"
    sequence_of = _hook(adapter, "sequence_of")
    if sequence_of is None:
        return _skip(name, "no sequence_of hook")
    events = ctx.get("events") or [
        {"id": "b", "seq": 2},
        {"id": "a", "seq": 1},
        {"id": "c", "seq": 3},
    ]
    try:
        ordered = sorted(events, key=sequence_of)
        keys = [sequence_of(e) for e in ordered]
    except Exception as exc:
        return _fail(name, f"sequence_of raised: {exc}")
    if keys != sorted(keys):
        return _fail(name, "sequence_of does not impose a monotonic order")
    return _ok(name, "out-of-order events sort deterministically by sequence")


def check_schema_drift(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """normalize() must tolerate an unexpected extra field (forward-compatible
    schema drift) without crashing. Skips when no normalize hook exists."""
    name = "schema_drift"
    normalize = _hook(adapter, "normalize")
    if normalize is None:
        return _skip(name, "no normalize hook")
    base = dict(ctx.get("normalize_sample", {"id": "x", "type": "t", "amount": "1.00"}))
    drifted = dict(base)
    drifted["__unexpected_new_field__"] = {"nested": [1, 2, 3]}
    try:
        normalize(drifted)
    except Exception as exc:
        return _fail(name, f"normalize crashed on an unexpected field: {exc}")
    return _ok(name, "normalize tolerated an unexpected extra field")


def check_malformed_input(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """normalize() must handle malformed input by returning empty/None or raising
    a controlled ValueError/KeyError/TypeError — never an uncontrolled crash.
    Skips when no normalize hook exists."""
    name = "malformed_input"
    normalize = _hook(adapter, "normalize")
    if normalize is None:
        return _skip(name, "no normalize hook")
    for bad in ({}, {"garbage": object()}, None):
        try:
            normalize(bad)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue  # controlled rejection is acceptable
        except Exception as exc:  # pragma: no cover - adapter bug surface
            return _fail(name, f"normalize raised an uncontrolled error on {bad!r}: {exc}")
    return _ok(name, "malformed input handled without an uncontrolled crash")


def check_idempotent_replay(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """The same input normalized twice must yield identical output. Skips when no
    normalize hook exists."""
    name = "idempotent_replay"
    normalize = _hook(adapter, "normalize")
    if normalize is None:
        return _skip(name, "no normalize hook")
    sample = ctx.get("normalize_sample", {"id": "x", "type": "t", "amount": "1.00"})
    try:
        first = normalize(dict(sample) if isinstance(sample, dict) else sample)
        second = normalize(dict(sample) if isinstance(sample, dict) else sample)
    except Exception as exc:
        return _fail(name, f"normalize raised during replay: {exc}")
    if repr(first) != repr(second):
        return _fail(name, "normalize is not idempotent for identical input")
    return _ok(name, "normalize is idempotent for identical input")


def check_health_transitions(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """A health hook must report an unconfigured adapter as not-healthy rather
    than claiming health without credentials. Skips when no health hook exists."""
    name = "health_transitions"
    health = _hook(adapter, "health")
    if health is None:
        return _skip(name, "no health hook")
    try:
        unconfigured = health({"configured": False})
    except Exception as exc:
        return _fail(name, f"health raised: {exc}")
    if isinstance(unconfigured, dict):
        healthy = unconfigured.get("healthy")
        state = str(unconfigured.get("state") or unconfigured.get("status") or "").lower()
    else:
        healthy = None
        state = str(unconfigured).lower()
    if healthy is True or state in ("ok", "healthy", "up"):
        return _fail(name, "unconfigured adapter reported healthy")
    return _ok(name, "health reflects configuration state")


def check_tenant_isolation(adapter: Any, ctx: dict) -> CertificationCheckResult:
    """When a builder/normalizer accepts a tenant, two tenants must yield
    tenant-scoped outputs that do not leak each other's identifiers. Skips when
    no tenant-aware hook is exposed."""
    name = "tenant_isolation"
    build = _hook(adapter, "build_request")
    if build is None:
        return _skip(name, "no tenant-aware build_request hook")
    ctx_a = {**ctx.get("sample_request", {}), "tenant_id": "tenant_A"}
    ctx_b = {**ctx.get("sample_request", {}), "tenant_id": "tenant_B"}
    try:
        req_a = build(ctx_a)
        req_b = build(ctx_b)
    except Exception as exc:
        return _fail(name, f"build_request raised for a tenant: {exc}")
    a_text = " ".join(_flatten_strings(req_a))
    b_text = " ".join(_flatten_strings(req_b))
    if "tenant_A" not in a_text or "tenant_B" not in b_text:
        return _skip(name, "build_request does not echo tenant scope")
    if "tenant_B" in a_text or "tenant_A" in b_text:
        return _fail(name, "cross-tenant identifier leaked between requests")
    return _ok(name, "requests are tenant-scoped with no cross-tenant leakage")


ALL_CHECKS = [
    check_descriptor_completeness,
    check_honest_status,
    check_unsupported_marked,
    check_secret_redaction,
    check_request_construction,
    check_auth_injection,
    check_timeout_declared,
    check_retry_declared,
    check_rate_limit_declared,
    check_pagination,
    check_cursor_persistence,
    check_duplicate_handling,
    check_out_of_order_handling,
    check_schema_drift,
    check_malformed_input,
    check_idempotent_replay,
    check_health_transitions,
    check_tenant_isolation,
]


def run_certification(
    adapter: Any,
    ctx: Optional[dict] = None,
    checks: Optional[list] = None,
) -> list[CertificationCheckResult]:
    """Run every certification check against an adapter, returning one result per
    check. A check that raises is recorded as a failure (never propagated)."""
    ctx = ctx or {}
    checks = checks if checks is not None else ALL_CHECKS
    results: list[CertificationCheckResult] = []
    for check in checks:
        try:
            results.append(check(adapter, ctx))
        except Exception as exc:  # pragma: no cover - defensive
            results.append(
                CertificationCheckResult(
                    name=getattr(check, "__name__", "unknown_check"),
                    passed=False,
                    detail=f"check raised: {exc}",
                )
            )
    return results


__all__ = [
    "CertificationCheckResult",
    "CertifiableAdapter",
    "ALL_CHECKS",
    "run_certification",
    "check_descriptor_completeness",
    "check_honest_status",
    "check_unsupported_marked",
    "check_secret_redaction",
    "check_request_construction",
    "check_auth_injection",
    "check_timeout_declared",
    "check_retry_declared",
    "check_rate_limit_declared",
    "check_pagination",
    "check_cursor_persistence",
    "check_duplicate_handling",
    "check_out_of_order_handling",
    "check_schema_drift",
    "check_malformed_input",
    "check_idempotent_replay",
    "check_health_transitions",
    "check_tenant_isolation",
]
