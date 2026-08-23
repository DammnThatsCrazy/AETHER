"""Commit 12-C — runtime readiness (deployment-gate projection).

Readiness answers one question: is this model-runtime instance safe to serve
traffic? It is the projection of ADR-008 D8 onto the deployment gate:

- Missing/unsafe configuration always fails readiness ("config not ok").
- An unhealthy runtime always fails readiness ("runtime unhealthy").
- A degraded runtime stays ready but carries warn-level provider blockers.
- Missing credentials are always *reported* as a blocker, and fail readiness
  only while the ``FailClosed`` gate is enabled. Per ADR-008 D9 every harness
  feature ships behind a feature flag default OFF, so the gate defaults
  disabled: deployments opt in to fail-closed credential gating at the
  staging/production cutover. Configuration and runtime health are never
  gated — they fail closed unconditionally.

Security: the report is audit-safe. Blocker reasons are terse, internally
generated strings and never include key material, secret values, or tenant
data (ADR-008 security invariants).
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Health contract (shared with Commit 12-B, services/model_runtime/
# observability/health.py). B's RuntimeHealthProbe yields a RuntimeHealth
# report:
#     status: "ok" | "degraded" | "unhealthy"
#     providers: per-provider health (iterable of names or {name: status})
#     checks: dict[name, bool | status-ish]
# RuntimeReadiness never hard-imports observability.health so this module
# loads cleanly while B's file lands; the structural contract is resolved
# defensively (a report object, a report-producing method, or a callable).
# ---------------------------------------------------------------------------


class RuntimeHealthProbe(Protocol):
    """Structural shape of Commit 12-B's runtime health surface.

    A probe yields a ``RuntimeHealth`` report carrying ``status`` (``"ok"``,
    ``"degraded"``, or ``"unhealthy"``), ``providers``, and ``checks``.
    ``RuntimeReadiness`` accepts the report object directly or any probe that
    produces one, so both B's live probe and test doubles work without a hard
    import.
    """

    status: str
    providers: Any
    checks: dict[str, Any]


# Statuses that count as a *passing* individual check. "degraded" and
# "skipped" mirror the gateway readiness probe: reported but non-blocking.
_OK_STATUSES = frozenset({"ok", "degraded", "skipped"})


class ReadinessState(BaseModel):
    """Immutable snapshot of one readiness evaluation.

    ``ready`` is the serve-traffic answer; ``blockers`` are the terse reasons
    (in evaluation order) and ``checks`` the per-dimension booleans
    (``config``, ``health``, ``credentials`` plus normalized health checks).
    """

    model_config = ConfigDict(frozen=True)

    ready: bool
    blockers: tuple[str, ...] = ()
    checks: dict[str, bool] = Field(default_factory=dict)


class FailClosed:
    """ADR-008 D8/D9 credential fail-closed gate.

    D8 says staging/production fail closed on missing credentials. D9 says
    every harness feature ships behind a feature flag default OFF. The gate
    reconciles the two: credential absence is *always* reported as a blocker,
    but only flips readiness to False while the gate is enabled. Deployments
    turn it on at the staging/production cutover; until then the runtime stays
    available (config and runtime health are never gated and fail closed
    unconditionally).

    ``__bool__`` mirrors ``enabled`` so ``if gate:`` reads naturally.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = bool(enabled)

    def permits(self, *, credentials_ok: bool) -> bool:
        """True when the gate allows serving given the credential health."""
        if not credentials_ok and self.enabled:
            return False
        return True

    def __bool__(self) -> bool:
        return self.enabled


class RuntimeReadiness:
    """Deployment-gate projection over a runtime health probe.

    Args:
        health: a RuntimeHealthProbe-like — a report object with ``status``/
            ``providers``/``checks``, or a probe exposing a report-producing
            method (``check``/``probe``/``evaluate``/``report``/``snapshot``)
            or callable. An unresolved probe (missing status, async-only,
            broken) fails closed rather than raising.
        credential_health: optional ``Callable[[], bool]``; None means
            credentials are not yet part of the gate. Commit 6's
            CredentialService/ProviderCredentialResolver is consumed only
            through this injected callable, so this module never imports the
            credentials package (which may not be landed yet).
        config_ok: True when the instance's configuration is present and
            safe. False always fails readiness (ADR-008 D8).
        fail_closed: the credential gate. Defaults to a disabled
            ``FailClosed()`` (D9 feature-flag default OFF).
    """

    def __init__(
        self,
        health: RuntimeHealthProbe,
        *,
        credential_health: Callable[[], bool] | None = None,
        config_ok: bool = True,
        fail_closed: FailClosed | None = None,
    ) -> None:
        self.health = health
        self.credential_health = credential_health
        self.config_ok = bool(config_ok)
        self.fail_closed = fail_closed if fail_closed is not None else FailClosed()

    def is_ready(self) -> bool:
        """Convenience: the ready bit of a fresh evaluation."""
        return self.evaluate().ready

    def evaluate(self) -> ReadinessState:
        """Evaluate readiness right now and return an immutable snapshot."""
        report = self._resolve_health()
        status = self._status(report)

        blockers: list[str] = []
        checks: dict[str, bool] = self._normalize_checks(self._checks(report))

        # Configuration — never gated; fail closed unconditionally (D8).
        if self.config_ok:
            checks["config"] = True
        else:
            checks["config"] = False
            blockers.append("config not ok")

        # Runtime health — never gated; unhealthy always fails closed.
        if status == "unhealthy":
            checks["health"] = False
            blockers.append("runtime unhealthy")
        elif status == "degraded":
            # Degraded still serves traffic but the degraded providers are
            # surfaced as warn-level blockers so operators can see them.
            checks["health"] = True
            for name in self._degraded_providers(self._providers(report), status):
                blockers.append(f"provider degraded: {name}")
        else:  # "ok"
            checks["health"] = True

        # Credentials — always reported; fails readiness only when the
        # FailClosed gate is enabled (D9 default OFF).
        cred_ok = True
        if self.credential_health is not None:
            try:
                cred_ok = bool(self.credential_health())
            except Exception:
                cred_ok = False
            checks["credentials"] = cred_ok
            if not cred_ok:
                blockers.append("credential health failed")
        else:
            checks["credentials"] = True

        ready = self._ready(status, cred_ok)
        return ReadinessState(ready=ready, blockers=tuple(blockers), checks=checks)

    # ── internals ───────────────────────────────────────────────────────────

    def _ready(self, status: str, cred_ok: bool) -> bool:
        if not self.config_ok or status == "unhealthy":
            return False
        return self.fail_closed.permits(credentials_ok=cred_ok)

    def _resolve_health(self) -> Any:
        """Resolve a health report from the probe defensively.

        Accepts a report object (has a non-callable ``status``), a probe with a
        report-producing method (B's ``RuntimeHealthProbe.status()`` included),
        or a callable probe. Anything else — including async-only probes,
        which cannot be awaited in this synchronous gate — resolves to None so
        the evaluation fails closed instead of raising.
        """
        probe = self.health
        if probe is None:
            return None
        status_attr = getattr(probe, "status", None)
        if status_attr is not None and not callable(status_attr):
            return probe  # report object: status is a plain value.
        for name in ("status", "check", "probe", "evaluate", "report", "snapshot"):
            method = getattr(probe, name, None)
            if callable(method):
                return self._settle(method())
        if callable(probe):
            return self._settle(probe())
        return None

    @staticmethod
    def _settle(result: Any) -> Any:
        if inspect.isawaitable(result):
            result.close()  # never awaited in the sync gate; fail closed.
            return None
        return result

    @staticmethod
    def _status(report: Any) -> str:
        if report is None:
            return "unhealthy"  # no report → fail closed.
        status = getattr(report, "status", None)
        if status is None:
            return "unhealthy"
        return str(status).lower()

    @staticmethod
    def _providers(report: Any) -> Any:
        if report is None:
            return ()
        return getattr(report, "providers", None) or ()

    @staticmethod
    def _checks(report: Any) -> Any:
        if report is None:
            return {}
        return getattr(report, "checks", None) or {}

    @staticmethod
    def _normalize_checks(checks: Any) -> dict[str, bool]:
        out: dict[str, bool] = {}
        if not isinstance(checks, dict):
            return out
        for key, value in checks.items():
            name = str(key)
            if isinstance(value, dict):
                status = value.get("status")
                if isinstance(status, str):
                    out[name] = status.lower() in _OK_STATUSES
                else:
                    out[name] = bool(value.get("ok", value.get("passed", True)))
            elif isinstance(value, bool):
                out[name] = value
            elif isinstance(value, str):
                out[name] = value.lower() in _OK_STATUSES
            else:
                out[name] = bool(value)
        return out

    @staticmethod
    def _degraded_providers(providers: Any, overall: str) -> list[str]:
        """Names of providers currently degraded (warn-level blockers only).

        Handles three provider shapes: ``{name: state}`` dicts, iterables of
        objects carrying ``healthy``/``status`` (Commit 12-B's
        ``ProviderHealth``), and plain name strings. A plain name with no
        per-provider signal attributes the overall degraded status to it.
        """
        degraded: list[str] = []
        if not providers:
            return degraded
        if isinstance(providers, dict):
            for name, state in providers.items():
                if RuntimeReadiness._status_of(state) == "degraded":
                    degraded.append(str(name))
            return degraded
        for entry in providers:
            name = RuntimeReadiness._provider_name(entry)
            healthy = getattr(entry, "healthy", None)
            state = (
                None
                if isinstance(entry, str)
                else RuntimeReadiness._status_of(getattr(entry, "status", None))
            )
            if isinstance(healthy, bool):
                if not healthy:
                    degraded.append(name)
            elif state is not None and state == "degraded":
                degraded.append(name)
            elif overall == "degraded":
                # Plain name and no per-provider signal → the overall degraded
                # status is the only signal; attribute it (warn-level).
                degraded.append(name)
        return degraded

    @staticmethod
    def _provider_name(entry: Any) -> str:
        if isinstance(entry, str):
            return entry
        return str(
            getattr(entry, "name", None)
            or getattr(entry, "provider_name", None)
            or getattr(entry, "provider", None)  # Commit 12-B ProviderHealth
            or "unknown"
        )

    @staticmethod
    def _status_of(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value.lower()
        if isinstance(value, dict):
            status = value.get("status")
            return str(status).lower() if isinstance(status, str) else None
        status = getattr(value, "status", None)
        return str(status).lower() if isinstance(status, str) else None


def describe(state: ReadinessState) -> str:
    """Audit-safe one-line readiness summary: ready bit, blocker count, first blocker.

    Blockers are terse, internally generated reasons and never include key
    material, secret values, or tenant data (ADR-008 security invariants), so
    this string is safe to emit into logs and runbook tooling.
    """
    first = state.blockers[0] if state.blockers else "none"
    return f"ready={state.ready} blockers={len(state.blockers)} first={first}"


__all__ = [
    "FailClosed",
    "ReadinessState",
    "RuntimeHealthProbe",
    "RuntimeReadiness",
    "describe",
]
