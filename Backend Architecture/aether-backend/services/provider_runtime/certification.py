"""Contract certification harness for the Universal Provider Runtime.

:func:`certify_provider` runs a fixed set of honesty checks against a provider
plugin and returns a :class:`~shared.integration_contracts.certification.CertificationReport`.
Every check produces a :class:`CertificationCheck` with an explicit pass/fail
verdict — a dishonest plugin must yield ``passed=False`` with a *failing* check,
never a false pass.

Honesty invariants enforced here:

* the identity parses and all three segments are non-empty;
* the manifest passes §32 ``validate_manifest``;
* the capability set is honest (``services.provider_runtime.validation.capability_violations``);
* the credential schema never declares a *secret* field as optional, and every
  field has a non-empty name;
* ``webhooks.supported`` implies a verification scheme AND a webhook adapter;
* the normalizer never raises on an opaque record (events or dropped);
* auth/pull adapters (when present) return an ``AdapterResult`` — never raise —
  for a no-credential context, without leaking secrets into ``safe_message``;
* declared outputs/destinations are non-empty, cleanly-parseable strings;
* readiness is never overclaimed: the report's readiness is the manifest's own
  claim verbatim, and the claimed ``level`` may never exceed the evidence its
  state token supports.

NO live network calls are made during certification: adapters are exercised with
a no-credential :class:`~shared.integration_contracts.acquisition.AcquisitionContext`
so a conforming adapter short-circuits without a network call. When an adapter's
no-credential behavior cannot be proven without a call, the check is recorded as
a structural check (adapter present + returns ``AdapterResult``) and the detail
says so.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.certification import (
    CertificationCheck,
    CertificationReport,
)
from shared.integration_contracts.identity import IdentityError, parse_identity
from shared.integration_contracts.manifest import (
    ManifestValidationError,
    validate_manifest,
)
from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.plugin import (
    PluginValidationError,
    plugin_identity_key,
)
from shared.integration_contracts.results import AdapterResult
from shared.integration_contracts.events import make_raw_record

__all__ = ["certify_provider"]


# Highest productization level a given readiness token's evidence supports.
# Readiness is NEVER upgraded by the harness — the report carries the manifest's
# claim as-is — but a manifest claiming a *level* beyond its state token's
# evidence is an overclaim and must fail certification.
_STATE_LEVEL_CEILING: dict[CredentialReadiness, int] = {
    CredentialReadiness.SCAFFOLDED: 1,
    CredentialReadiness.CREDENTIAL_WAITING: 2,
    CredentialReadiness.REPLAY_VALIDATED: 3,
    CredentialReadiness.SANDBOX_VALIDATED: 4,
    CredentialReadiness.PARTNER_LIVE: 5,
    CredentialReadiness.DEGRADED: 2,
    CredentialReadiness.DISABLED: 1,
}


def _capability_violations(plugin: Any) -> list[str]:
    """Delegate to Team A's capability-honesty validator.

    Kept behind a module-level indirection so tests can inject a fake without
    importing Team A's module. Raises ``ImportError`` (loudly) when the contract
    validator is not installed.
    """
    from services.provider_runtime.validation import capability_violations

    return capability_violations(plugin)


def _run_async(coro_factory: Any) -> Any:
    """Run a coroutine from this sync harness.

    Uses ``asyncio.run`` when no loop is running; when a loop IS already running
    (e.g. inside an async test), the coroutine is run in a private worker-thread
    loop so the sync harness never deadlocks the caller's loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro_factory()).result()


def _resolve_identity(plugin: Any) -> str:
    """Best-effort canonical identity, tolerating broken plugins.

    Prefers the cross-checked ``plugin_identity_key``; falls back to the plugin's
    own identity/manifest surfaces. Never raises — a broken plugin surfaces as a
    failed ``identity_wellformed`` check instead of crashing the harness.
    """
    try:
        return plugin_identity_key(plugin)
    except (PluginValidationError, AttributeError):
        pass
    try:
        return str(plugin.identity().key)  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        return str(plugin.manifest().identity_key)  # type: ignore[attr-defined]
    except Exception:
        pass
    return "unknown"


def _plugin_version(plugin: Any) -> str:
    """Plugin version attribute/accessor, or ``""`` when absent."""
    value = getattr(plugin, "version", None)
    if callable(value):
        try:
            value = value()
        except Exception:
            value = None
    if not value:
        value = getattr(plugin, "plugin_version", None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
    return str(value) if value else ""


def _check_passed(name: str, detail: str = "") -> CertificationCheck:
    return CertificationCheck(name=name, passed=True, detail=detail)


def _check_failed(name: str, detail: str) -> CertificationCheck:
    return CertificationCheck(name=name, passed=False, detail=detail)


def _safe_failure_detail(exc: Exception, *, fallback: str) -> str:
    """Build a check-failure detail from an exception WITHOUT leaking secrets.

    Only ``safe_message`` (Team D) is ever used; the raw exception string and
    its ``details`` dict are deliberately never surfaced.
    """
    safe = getattr(exc, "safe_message", None)
    if isinstance(safe, str) and safe.strip():
        return f"{fallback}: {safe}"
    return fallback


# ── Individual checks ──────────────────────────────────────────────────────


async def _identity_wellformed(plugin: Any) -> CertificationCheck:
    try:
        key = plugin_identity_key(plugin)
        identity = parse_identity(key)
    except (PluginValidationError, IdentityError, AttributeError, ValueError) as exc:
        return _check_failed(
            "identity_wellformed",
            f"plugin identity does not parse to family.product.capability: "
            f"{_safe_failure_detail(exc, fallback='invalid identity')}",
        )
    parts = (identity.family, identity.product, identity.capability)
    if not all(str(p).strip() for p in parts):
        return _check_failed(
            "identity_wellformed",
            f"identity {key!r} has an empty segment",
        )
    return _check_passed("identity_wellformed", f"identity {key!r} is well-formed")


async def _manifest_honest(plugin: Any) -> CertificationCheck:
    try:
        manifest = plugin.manifest()  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "manifest_honest",
            _safe_failure_detail(exc, fallback="manifest() raised"),
        )
    try:
        validate_manifest(manifest)
    except ManifestValidationError as exc:
        violations = "; ".join(exc.violations)
        return _check_failed("manifest_honest", f"manifest violates §32 honesty: {violations}")
    except Exception as exc:  # pragma: no cover - defensive
        return _check_failed(
            "manifest_honest",
            _safe_failure_detail(exc, fallback="manifest validation raised"),
        )
    return _check_passed("manifest_honest", "manifest passes §32 honesty validation")


async def _capability_honest(plugin: Any) -> CertificationCheck:
    try:
        violations = list(_capability_violations(plugin))
    except Exception as exc:
        return _check_failed(
            "capability_honest",
            _safe_failure_detail(exc, fallback="capability_violations raised"),
        )
    if violations:
        return _check_failed(
            "capability_honest", f"capability overclaims: {'; '.join(str(v) for v in violations)}"
        )
    return _check_passed("capability_honest", "capability set matches adapter accessors")


async def _credential_schema_honest(plugin: Any) -> CertificationCheck:
    try:
        schema = plugin.manifest().authentication.credential_schema  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "credential_schema_honest",
            _safe_failure_detail(exc, fallback="credential schema unavailable"),
        )
    violations: list[str] = []
    for field in schema:
        name = str(getattr(field, "name", "") or "").strip()
        if not name:
            violations.append("a credential field has an empty name")
        secret = bool(getattr(field, "secret", False))
        required = bool(getattr(field, "required", False))
        if secret and not required:
            violations.append(f"secret field {name!r} is declared optional (required=False)")
    if violations:
        return _check_failed("credential_schema_honest", "; ".join(violations))
    return _check_passed(
        "credential_schema_honest",
        "every secret credential field is required and all field names are non-empty",
    )


async def _webhook_scheme_honest(plugin: Any) -> CertificationCheck:
    try:
        webhooks = plugin.manifest().webhooks  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "webhook_scheme_honest",
            _safe_failure_detail(exc, fallback="webhooks declaration unavailable"),
        )
    if not bool(getattr(webhooks, "supported", False)):
        return _check_passed("webhook_scheme_honest", "webhooks not declared; nothing to verify")
    scheme = str(getattr(webhooks, "verification_scheme", "") or "").strip()
    if not scheme:
        return _check_failed(
            "webhook_scheme_honest",
            "webhooks.supported=True requires a non-empty verification_scheme",
        )
    try:
        adapter = plugin.webhook()  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "webhook_scheme_honest",
            _safe_failure_detail(exc, fallback="webhook adapter accessor raised"),
        )
    if adapter is None:
        return _check_failed(
            "webhook_scheme_honest",
            f"manifest claims webhooks (scheme={scheme!r}) but no webhook adapter is present",
        )
    return _check_passed(
        "webhook_scheme_honest", f"webhook scheme {scheme!r} declared and adapter present"
    )


async def _normalizer_roundtrip(plugin: Any) -> CertificationCheck:
    identity = _resolve_identity(plugin)
    record = make_raw_record(
        provider_identity=identity,
        provider_record_id="__cert_probe__",
        provider_record_type="certification_probe",
        payload={"opaque": True, "certification": "probe"},
    )
    try:
        normalizer = plugin.normalizer()  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "normalizer_roundtrip",
            _safe_failure_detail(exc, fallback="normalizer() accessor raised"),
        )
    if normalizer is None:
        return _check_failed("normalizer_roundtrip", "plugin exposes no normalizer")
    try:
        result = normalizer.normalize(record)
    except Exception as exc:
        return _check_failed(
            "normalizer_roundtrip",
            _safe_failure_detail(exc, fallback="normalizer raised on an opaque record"),
        )
    if not isinstance(result, NormalizationResult):
        return _check_failed(
            "normalizer_roundtrip",
            f"normalizer returned {type(result).__name__}, expected NormalizationResult",
        )
    dropped = len(result.dropped)
    events = len(result.events)
    return _check_passed(
        "normalizer_roundtrip",
        f"normalizer returned a NormalizationResult ({events} events, {dropped} dropped)",
    )


async def _auth_contract(plugin: Any) -> CertificationCheck:
    try:
        auth = plugin.auth()  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "auth_contract",
            _safe_failure_detail(exc, fallback="auth adapter accessor raised"),
        )
    if auth is None:
        return _check_passed("auth_contract", "no auth adapter declared; nothing to verify")
    identity = _resolve_identity(plugin)
    context = AcquisitionContext(tenant_id="__cert__", provider_identity=identity, credential=None)
    try:
        result = await auth.validate_credentials(context)
    except Exception as exc:
        return _check_failed(
            "auth_contract",
            _safe_failure_detail(
                exc,
                fallback="auth adapter raised for a no-credential context (never a network call)",
            ),
        )
    if not isinstance(result, AdapterResult):
        return _check_failed(
            "auth_contract",
            f"auth adapter returned {type(result).__name__}, expected AdapterResult",
        )
    # Structural no-credential check: the adapter short-circuited with a result
    # (typically not_supported / unauthorized) without raising. Whether it made
    # a network call cannot be proven here; the no-credential contract is that
    # it MUST NOT need one.
    return _check_passed(
        "auth_contract",
        f"auth adapter returned AdapterResult(status={result.status.value}) "
        "for a no-credential context",
    )


async def _pull_contract(plugin: Any) -> CertificationCheck:
    try:
        pull = plugin.pull()  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "pull_contract",
            _safe_failure_detail(exc, fallback="pull adapter accessor raised"),
        )
    if pull is None:
        return _check_passed("pull_contract", "no pull adapter declared; nothing to verify")
    identity = _resolve_identity(plugin)
    context = AcquisitionContext(tenant_id="__cert__", provider_identity=identity, credential=None)
    try:
        result = await pull.fetch(context, cursor=None)
    except Exception as exc:
        return _check_failed(
            "pull_contract",
            _safe_failure_detail(
                exc,
                fallback="pull adapter raised for a no-credential context (never a network call)",
            ),
        )
    if not isinstance(result, AdapterResult):
        return _check_failed(
            "pull_contract",
            f"pull adapter returned {type(result).__name__}, expected AdapterResult",
        )
    return _check_passed(
        "pull_contract",
        f"pull adapter returned AdapterResult(status={result.status.value}) "
        "for a no-credential context",
    )


def _clean_output(value: Any) -> Optional[str]:
    """A claim is clean when it is a non-empty string with no stray whitespace."""
    if not isinstance(value, str):
        return f"output {value!r} is not a string"
    stripped = value.strip()
    if not stripped:
        return "output entry is empty"
    if stripped != value:
        return f"output {value!r} has leading/trailing whitespace"
    if any(ch in value for ch in "\r\n\t"):
        return f"output {value!r} contains control whitespace"
    return None


async def _outputs_claimed(plugin: Any) -> CertificationCheck:
    try:
        manifest = plugin.manifest()  # type: ignore[attr-defined]
        outputs = list(getattr(manifest, "data_outputs", None) or [])
        destinations = list(getattr(manifest, "product_destinations", None) or [])
    except Exception as exc:
        return _check_failed(
            "outputs_claimed",
            _safe_failure_detail(exc, fallback="data_outputs/product_destinations unavailable"),
        )
    problems: list[str] = []
    for claim in (*outputs, *destinations):
        problem = _clean_output(claim)
        if problem:
            problems.append(problem)
    if problems:
        return _check_failed("outputs_claimed", "; ".join(problems))
    return _check_passed(
        "outputs_claimed",
        f"{len(outputs)} data output(s) and {len(destinations)} product destination(s) are clean",
    )


async def _readiness_not_overclaimed(plugin: Any) -> CertificationCheck:
    try:
        readiness = plugin.manifest().readiness  # type: ignore[attr-defined]
    except Exception as exc:
        return _check_failed(
            "readiness_not_overclaimed",
            _safe_failure_detail(exc, fallback="readiness declaration unavailable"),
        )
    raw_level = getattr(readiness, "level", 0)
    try:
        level = int(raw_level)
    except (TypeError, ValueError):
        return _check_failed(
            "readiness_not_overclaimed",
            f"readiness.level={raw_level!r} is not a valid integer level",
        )
    state = getattr(readiness, "state", None)
    if not 1 <= level <= 5:
        return _check_failed(
            "readiness_not_overclaimed",
            f"readiness.level={level} is outside the allowed 1..5 range",
        )
    ceiling = _STATE_LEVEL_CEILING.get(state)
    if ceiling is not None and level > ceiling:
        return _check_failed(
            "readiness_not_overclaimed",
            f"readiness.level={level} exceeds the evidence for state={state!r} "
            f"(max {ceiling}); the manifest overclaims productization",
        )
    return _check_passed(
        "readiness_not_overclaimed",
        f"readiness.level={level} matches state={state!r} evidence (never upgraded)",
    )


# ── The harness ────────────────────────────────────────────────────────────


async def _run_checks(plugin: Any) -> list[CertificationCheck]:
    return [
        await _identity_wellformed(plugin),
        await _manifest_honest(plugin),
        await _capability_honest(plugin),
        await _credential_schema_honest(plugin),
        await _webhook_scheme_honest(plugin),
        await _normalizer_roundtrip(plugin),
        await _auth_contract(plugin),
        await _pull_contract(plugin),
        await _outputs_claimed(plugin),
        await _readiness_not_overclaimed(plugin),
    ]


def certify_provider(plugin: Any, *, environment: str = "local") -> CertificationReport:
    """Certify one provider plugin against the fixed contract surface.

    Returns a :class:`CertificationReport` whose ``readiness`` is the manifest's
    own claim VERBATIM — the harness never upgrades readiness. ``passed`` is the
    conjunction of every check; a dishonest plugin yields ``passed=False`` with a
    failing check, never a false pass.
    """
    identity = _resolve_identity(plugin)
    checks = _run_async(lambda: _run_checks(plugin))

    manifest_readiness = None
    try:
        manifest_readiness = plugin.manifest().readiness  # type: ignore[attr-defined]
    except Exception:
        pass
    if manifest_readiness is None:
        from shared.integration_contracts.manifest import ManifestReadiness

        manifest_readiness = ManifestReadiness(
            state=CredentialReadiness.SCAFFOLDED, level=1
        )

    return CertificationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        identity=identity,
        plugin_version=_plugin_version(plugin),
        readiness=manifest_readiness,
        environment=environment,
        checks=checks,
        passed=all(check.passed for check in checks),
    )
