"""Canonicalisation, digesting, and *located* divergence.

This module answers one question: did Aether and the Tenant Mirror return the
same tenant-visible value? Answering it honestly means separating two things
that a naive ``==`` conflates:

* **representation** — key order, timestamp spelling, ``1`` versus ``1.0``,
  a per-response request id. None of these are values a tenant can observe as
  different, and treating them as divergence produces false alarms that train
  operators to ignore the gate.
* **value** — a count, an identifier, a state, a list's order. A difference
  here means the operator is looking at a different system than the tenant
  runs, which is the exact failure the mirror exists to remove.

So a payload is first reduced to a canonical form (representation collapsed),
and only then hashed and compared. Two consequences worth stating:

``timestamp`` is deliberately **not** a presentation key. Response-envelope
clocks (``generated_at``, ``computed_at``, ``request_id``) are stripped because
they change on every call by construction, but a field literally named
``timestamp`` is very often the tenant's own event time, and stripping it would
hide a real divergence behind a rule meant to remove noise. Presentation keys
are a shrink-only list for that reason: adding one is an admission that a value
is not a value.

List order is preserved. A ranked list is a value — "who is on top" is
precisely what a tenant sees — so ordering differences inside arrays are
divergence, while key ordering inside objects is not.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from shared.common.common import BadRequestError
from shared.temporal.instant import to_iso_utc, try_parse_instant

from .contracts import Divergence, ParityComparison, ParityDigest

#: Domain separator. A digest is only ever compared with another digest from
#: this same function; the prefix stops a raw SHA-256 of the same bytes,
#: computed by some other tool, from being mistaken for a parity proof.
_DIGEST_DOMAIN = "aether.kyber.tenant-mirror.parity.v1"

#: Most divergences an incident responder can act on in one sitting. Beyond
#: this the list is capped and ``ParityComparison.truncated`` says so.
MAX_REPORTED_DIVERGENCES = 50

#: Keys removed at every depth before digesting, each with the reason it is not
#: a value. This mapping *is* the list — :data:`PRESENTATION_KEYS` is derived
#: from it — so a key can never be added without stating why.
#:
#: The rule for adding one: the key must change between two calls that returned
#: the same tenant-visible result. If it can differ while the result is the
#: same, it is presentation. If it can differ *because* the result differs, it
#: is a value and belongs in the digest.
PRESENTATION_KEY_REASONS: dict[str, str] = {
    # Per-response identifiers. `APIResponse` mints a fresh uuid4 per call, so
    # these differ on every single request by construction.
    "request_id": "APIResponse mints a fresh uuid4 per response",
    "requestId": "camelCase twin of request_id used by the TS clients",
    "trace_id": "per-request telemetry correlation, not a tenant value",
    "traceId": "camelCase twin of trace_id",
    "correlation_id": "per-request telemetry correlation, not a tenant value",
    "correlationId": "camelCase twin of correlation_id",
    # Render-time clocks. Named for the moment the *response* was built, never
    # for a moment in the tenant's data. `timestamp` is excluded on purpose.
    "generated_at": "wall clock at render time; advances between two identical reads",
    "generatedAt": "camelCase twin of generated_at",
    "computed_at": "wall clock at diagnostic-computation time",
    "computedAt": "camelCase twin of computed_at",
    "rendered_at": "wall clock at serialisation time",
    "renderedAt": "camelCase twin of rendered_at",
    "response_timestamp": "envelope clock; the tenant's own times are separate fields",
    # Layout hints. The row's identity and values are carried by its own fields;
    # these only tell a client where to draw it.
    "sort_index": "client layout hint; the ordered array itself carries the order",
    "sortIndex": "camelCase twin of sort_index",
    "display_order": "client layout hint",
    "displayOrder": "camelCase twin of display_order",
    "row_index": "client layout hint; position is already the array index",
    "rowIndex": "camelCase twin of row_index",
    # A label rendered *from* values that are themselves in the payload. If a
    # label is the only carrier of a number, that is a payload defect: the
    # number must be a field, and this entry must be removed.
    "display_label": "string rendered from values that are themselves digested",
    "displayLabel": "camelCase twin of display_label",
}

#: The stripped keys. Shrink-only: removing one strengthens the digest, adding
#: one weakens it and requires a reason above.
PRESENTATION_KEYS: frozenset[str] = frozenset(PRESENTATION_KEY_REASONS)

#: Keys that must never be treated as presentation, whatever a future edit
#: claims. Every one of them routinely carries a tenant-observable value, and
#: stripping it would make the digest agree while the tenant sees a difference.
#: ``scripts/validate_tenant_mirror_parity.py`` enforces the disjointness.
VALUE_BEARING_KEYS: frozenset[str] = frozenset({
    "amount", "balance", "count", "created_at", "currency", "email", "id",
    "name", "occurred_at", "score", "state", "status", "timestamp", "total",
    "updated_at", "value", "vertex_id", "vertex_type",
})


# ── Canonicalisation ─────────────────────────────────────────────────────────


def _canonical_number(value: Any) -> Any:
    """Collapse numeric representation without collapsing numeric value.

    ``1``, ``1.0`` and ``Decimal("1.0")`` are the same number rendered by three
    serialisers; reporting them as divergence would be noise. ``0.1`` and
    ``0.30000000000000004`` are different numbers and stay different.

    Non-finite floats cannot be expressed in JSON at all. They are mapped to a
    visible sentinel rather than raising, because a comparison run during an
    incident must still produce a located answer — and the sentinel shows up in
    the canonical form, so it is reported, not swallowed.
    """
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return "__nonfinite__:nan"
        if value in (float("inf"), float("-inf")):
            return f"__nonfinite__:{'inf' if value > 0 else '-inf'}"
        if value == int(value):
            return int(value)  # also folds -0.0 to 0
        return value
    return int(value)


def _canonical_string(value: str) -> str:
    """Normalise a string, rewriting it only when it is an exact instant.

    ``2026-01-01T00:00:00+00:00`` and ``2026-01-01T00:00:00Z`` are the same
    moment spelled two ways. ``try_parse_instant`` is strict — it rejects naive
    and malformed values — so anything that is not unambiguously an instant is
    left exactly as it was rather than being guessed at.
    """
    parsed, _reason = try_parse_instant(value)
    if parsed is None:
        return value
    return to_iso_utc(parsed)


def _canonicalize(value: Any, path: str) -> Any:
    """Reduce one node to canonical form, carrying its path for error messages."""
    if value is None or isinstance(value, bool):
        return value  # bool before int: bool is a subclass of int
    if isinstance(value, str):
        return _canonical_string(value)
    if isinstance(value, (int, float, Decimal)):
        return _canonical_number(value)
    if isinstance(value, datetime):
        return to_iso_utc(value)
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item, f"{path}.{key}")
            for key, item in value.items()
            if str(key) not in PRESENTATION_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _canonicalize(model_dump(), path)
    # Falling back to str() here is how a type mismatch would become an
    # invisible "equal". Refuse instead, naming the path and the type.
    raise BadRequestError(
        f"tenant-visible payload carries a non-serialisable value at {path}",
        details={"path": path, "type": type(value).__name__},
    )


def canonical_payload(payload: Any) -> str:
    """The deterministic string form of a tenant-visible payload.

    Object keys sorted, presentation keys removed at every depth, instants
    normalised to UTC ``Z``, numbers collapsed to one representation, array
    order preserved, no incidental whitespace. Two payloads with the same
    canonical form are the same tenant-visible result.
    """
    canonical = _canonicalize(payload, "$")
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest_tenant_visible(payload: Any, *, contract_version: str) -> ParityDigest:
    """SHA-256 over the canonical form *and* the contract version.

    Binding the contract version into the hashed material — rather than storing
    it beside the hash — means a contract bump can never read as parity. The
    same bytes under ``1.0.0`` and ``1.1.0`` describe different things, and a
    digest that ignored that would quietly certify a stale mirror as correct.
    """
    canonical = canonical_payload(payload)
    material = f"{_DIGEST_DOMAIN}\ncontract_version={contract_version}\n{canonical}"
    return ParityDigest(
        digest=hashlib.sha256(material.encode("utf-8")).hexdigest(),
        canonical_bytes=len(canonical.encode("utf-8")),
        contract_version=str(contract_version),
    )


# ── Located divergence ───────────────────────────────────────────────────────


_MISSING = object()


def _kind(value: Any) -> str:
    """The JSON kind of a canonical value.

    Numbers are one kind: after canonicalisation an ``int`` and a ``float`` are
    both numbers that happen to differ in whether they are integral, so calling
    ``2`` versus ``2.5`` a *type* difference would misdescribe it.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _walk(aether: Any, mirror: Any, path: str, found: list[Divergence]) -> None:
    """Collect every divergence between two already-canonical structures.

    The whole tree is walked even after the cap is reached, because
    ``divergence_count`` has to be the real total: an operator told "3
    divergences" when there are 300 will size the incident wrong.
    """
    if isinstance(aether, dict) and isinstance(mirror, dict):
        for key in sorted(set(aether) | set(mirror)):
            left = aether.get(key, _MISSING)
            right = mirror.get(key, _MISSING)
            child = f"{path}.{key}"
            if left is _MISSING:
                found.append(
                    Divergence(path=child, aether=None, mirror=right, reason="missing_in_aether")
                )
            elif right is _MISSING:
                found.append(
                    Divergence(path=child, aether=left, mirror=None, reason="missing_in_mirror")
                )
            else:
                _walk(left, right, child, found)
        return

    if isinstance(aether, list) and isinstance(mirror, list):
        if len(aether) != len(mirror):
            found.append(
                Divergence(
                    path=path,
                    aether=len(aether),
                    mirror=len(mirror),
                    reason="length_differs",
                )
            )
        for index in range(min(len(aether), len(mirror))):
            _walk(aether[index], mirror[index], f"{path}[{index}]", found)
        return

    # A present value against an absent one is a value difference, not a type
    # difference — "the mirror lost this field" is what the operator needs read.
    if _kind(aether) != _kind(mirror) and aether is not None and mirror is not None:
        found.append(
            Divergence(path=path, aether=aether, mirror=mirror, reason="type_differs")
        )
        return

    if aether != mirror:
        found.append(
            Divergence(path=path, aether=aether, mirror=mirror, reason="value_differs")
        )


def compare(
    aether_payload: Any,
    mirror_payload: Any,
    *,
    contract_version: str,
) -> ParityComparison:
    """Compare two tenant-visible payloads and say exactly where they disagree.

    The comparison runs over the *canonical* forms, so it reports the same
    differences the digest reacts to and nothing else — a divergence list that
    disagreed with the digest would leave an operator unable to trust either.
    """
    aether_digest = digest_tenant_visible(aether_payload, contract_version=contract_version)
    mirror_digest = digest_tenant_visible(mirror_payload, contract_version=contract_version)
    if aether_digest.digest == mirror_digest.digest:
        return ParityComparison(
            matched=True,
            contract_version=str(contract_version),
            aether_digest=aether_digest,
            mirror_digest=mirror_digest,
        )

    found: list[Divergence] = []
    _walk(_canonicalize(aether_payload, "$"), _canonicalize(mirror_payload, "$"), "$", found)

    # A digest mismatch with no located divergence is a bug in this module, not
    # a clean bill of health, so it is reported as one rather than as parity.
    if not found:
        found.append(
            Divergence(
                path="$",
                aether=aether_digest.digest,
                mirror=mirror_digest.digest,
                reason="value_differs",
            )
        )

    return ParityComparison(
        matched=False,
        contract_version=str(contract_version),
        aether_digest=aether_digest,
        mirror_digest=mirror_digest,
        divergences=found[:MAX_REPORTED_DIVERGENCES],
        divergence_count=len(found),
        truncated=len(found) > MAX_REPORTED_DIVERGENCES,
    )


__all__ = [
    "MAX_REPORTED_DIVERGENCES",
    "PRESENTATION_KEYS",
    "PRESENTATION_KEY_REASONS",
    "VALUE_BEARING_KEYS",
    "canonical_payload",
    "compare",
    "digest_tenant_visible",
]
