"""The install verifier — did the snippet a tenant pasted actually come up?

The problem this exists for: an install that delivers nothing looks exactly
like an install that was never pasted, because both produce silence. A tenant
who copies the snippet, ships it, and sees no data cannot tell whether they got
the key wrong, whether a CSP header blocked the loader, or whether they are
simply looking at a dashboard before the first event arrived.

So the loader reports its own milestones (see ``packages/web/src/loader/
heartbeat.ts``): ``sdk_loaded`` when the bundle ran, ``sdk_initialized`` when
the SDK accepted its config, and ``sdk_init_failed`` when it did not. Those ride
the ordinary ``/v1/batch`` contract as ``core``-family events. This module reads
them back out of accepted ingestion and folds them onto the site they name.

Three deliberate properties:

* **It runs off accepted ingestion, not off a separate endpoint.** The signals
  are events like any other, so the verifier cannot report an install as healthy
  on evidence that ingestion itself rejected.
* **It never fails ingestion.** It is called after Bronze durability, and a
  projection bug must not turn into a 503 for a tenant's event stream. Failures
  are logged and metered, never raised.
* **It records what was observed, not what was hoped for.** A site with no
  signals has no record; that absence is the finding, and the read endpoints
  report it as ``awaiting_first_signal`` rather than inventing a status.

Distinct from ``services/sdk_drift``: that detector runs on health-agent
heartbeats from already-installed SDKs and looks for schema/stale/replay drift.
This one runs on the install handshake, before there is an SDK to send a
heartbeat, and its subject is the site rather than the installation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Sequence

from repositories.sdk_repos import SITE_INSTALL_RECORD_TYPE
from shared.logger.logger import get_logger, metrics

from services.sdk_distribution.versions import describe_install_version

logger = get_logger("aether.service.sdk_distribution.install_verifier")

# The loader's milestones, in the order a working install produces them.
SIGNAL_LOADED = "sdk_loaded"
SIGNAL_INITIALIZED = "sdk_initialized"
SIGNAL_FAILED = "sdk_init_failed"

INSTALL_SIGNAL_TYPES: frozenset[str] = frozenset(
    {SIGNAL_LOADED, SIGNAL_INITIALIZED, SIGNAL_FAILED}
)

# Site install status — what the stored record says the site is.
STATUS_LOADED = "loaded"
STATUS_LIVE = "live"
STATUS_FAILED = "failed"

# Install state — what the verifier reports when asked. One extra value beyond
# the stored statuses: a site with no record at all.
STATE_LOADED = "loaded"
STATE_LIVE = "live"
STATE_FAILED = "failed"
STATE_AWAITING = "awaiting_first_signal"

#: The loader's milestones in the order a working install produces them; the
#: read endpoints publish this so a dashboard can render the handshake without
#: hardcoding the sequence a second time.
SIGNAL_ORDER: tuple[str, ...] = (SIGNAL_LOADED, SIGNAL_INITIALIZED, SIGNAL_FAILED)

#: How long an operator should wait before treating silence as a problem. The
#: loader fires `sdk_loaded` on script execution, so this is generous for a
#: handshake and short enough to be worth watching — the value the install page
#: quotes, kept here so the page and the verifier cannot disagree.
FIRST_SIGNAL_WINDOW_SECONDS = 60


def install_signal(normalized: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The install-signal facts in one accepted event, or None.

    Returns None for every ordinary event — this is called on all accepted
    ingestion, so the common case has to be a cheap miss.
    """
    if normalized.get("event_type") not in INSTALL_SIGNAL_TYPES:
        return None

    properties = normalized.get("properties") or {}
    if not isinstance(properties, dict):
        return None
    site_id = properties.get("siteId")
    if not site_id or not isinstance(site_id, str):
        # A signal with no site cannot be attributed to one, and guessing the
        # tenant's only site would misattribute it in exactly the case the
        # operator is trying to debug (a snippet pasted without its data-site).
        return None

    context = normalized.get("context") or {}
    library = context.get("library") if isinstance(context, dict) else None
    library = library if isinstance(library, dict) else {}

    warnings = properties.get("warnings")
    return {
        "site_id": site_id,
        "signal": normalized["event_type"],
        # The loader states its own version in both places; properties wins
        # because it is the field the loader documents for this purpose, and
        # context.library is the SDK-wide block it also has to fill.
        "loader_version": properties.get("loaderVersion") or library.get("version"),
        "library_name": library.get("name"),
        "sdk_version": properties.get("sdkVersion"),
        "install_mode": properties.get("installMode"),
        "reason": properties.get("reason"),
        "warnings": [str(w) for w in warnings] if isinstance(warnings, list) else [],
        "occurred_at": normalized.get("timestamp") or normalized.get("received_at"),
    }


def merge_site_install(
    existing: Optional[dict[str, Any]],
    facts: Sequence[dict[str, Any]],
    tenant_id: str,
) -> dict[str, Any]:
    """Fold one batch's install signals into a site's install record.

    Pure, so the interesting part — that a failure after a success is visible,
    that a later success clears an earlier failure, that unknown optional fields
    do not erase known ones — is testable without a database.

    ``existing`` is the stored record (or None on first signal); ``facts`` are
    this batch's signals for one site, already in arrival order. A single batch
    legitimately carries both ``sdk_loaded`` and ``sdk_initialized``.
    """
    record: dict[str, Any] = dict(existing or {})
    signals: dict[str, Any] = dict(record.get("signals") or {})

    for fact in facts:
        signal = fact["signal"]
        previous = signals.get(signal) or {}
        signals[signal] = {
            "count": int(previous.get("count", 0)) + 1,
            "first_at": previous.get("first_at") or fact["occurred_at"],
            "last_at": fact["occurred_at"],
            # Kept only on the failure signal: on a success these are absent,
            # and keeping the last non-empty value would preserve a stale
            # warning after the operator fixed it.
            **({"reason": fact["reason"]} if fact.get("reason") else {}),
            **({"warnings": fact["warnings"]} if fact.get("warnings") else {}),
        }

    last = facts[-1]
    record.update(
        {
            "tenant_id": tenant_id,
            "installation_id": last["site_id"],
            "record_type": SITE_INSTALL_RECORD_TYPE,
            "site_id": last["site_id"],
            # Only overwrite what this batch actually reported: a later
            # `sdk_init_failed` carries no installMode, and blanking the mode
            # captured from the successful load would lose the one field that
            # says which install path the site is on.
            **{k: v for k, v in {
                "install_mode": last.get("install_mode"),
                "sdk_version": last.get("sdk_version"),
            }.items() if v},
            "signals": signals,
            "last_signal": last["signal"],
            "last_signal_at": last["occurred_at"],
            "last_seen": last["occurred_at"],
            "status": _status_after(last, signals),
        }
    )
    record.update(
        describe_install_version(
            last.get("loader_version") or record.get("loader_version"),
            last.get("library_name"),
        )
    )
    if not record.get("first_signal_at"):
        record["first_signal_at"] = facts[0]["occurred_at"]
    return record


def _status_after(last: dict[str, Any], signals: dict) -> str:
    """The site's current status given its whole signal history.

    A failure is only current until something succeeds after it — otherwise a
    site that was broken last month and fixed since would be reported as broken
    forever, which trains operators to ignore the field. So the newest signal
    decides, with the caveat that ``sdk_loaded`` is a weaker fact than an
    initialization that has already happened.
    """
    if last["signal"] == SIGNAL_FAILED:
        return STATUS_FAILED
    return STATUS_LIVE if SIGNAL_INITIALIZED in signals else STATUS_LOADED


async def record_install_signals(
    tenant_id: str,
    normalized_events: Sequence[dict[str, Any]],
    declared_site: Optional[str] = None,
) -> int:
    """Project a batch's install signals onto their sites. Returns how many sites.

    Never raises: this is called after Bronze durability, so a projection bug
    must not become a failed request for a tenant whose events are already
    safe. The cost of a lost projection is one stale verifier reading, against
    the cost of a 503 on real ingestion.

    ``declared_site`` is the site the request authenticated as, already checked
    against the credential's binding by the route policy. A signal naming a
    different site is refused rather than projected, and this is load-bearing:
    ``properties.siteId`` comes from the event body, which the caller writes. A
    publishable key is public in page HTML, so without this check a key copied
    off one customer's page could report install state for another of the
    tenant's sites — turning the one field that exists to be trustworthy into
    one any page's reader can forge. When no site was declared the credential is
    tenant-wide by design (a secret key), and no confinement applies.
    """
    facts: dict[str, list[dict[str, Any]]] = {}
    mismatched = 0
    for normalized in normalized_events:
        fact = install_signal(normalized)
        if fact is None:
            continue
        if declared_site and fact["site_id"] != declared_site:
            mismatched += 1
            continue
        facts.setdefault(fact["site_id"], []).append(fact)

    if mismatched:
        logger.warning(
            "Install signal(s) named a site the request did not authenticate as: "
            "tenant=%s declared=%s refused=%d",
            tenant_id,
            declared_site,
            mismatched,
        )
        metrics.increment(
            "sdk_install_signal_site_mismatch_total",
            value=mismatched,
            labels={"tenant_id": tenant_id},
        )

    if not facts:
        # The overwhelmingly common case: an ordinary batch of tenant events.
        return 0

    from repositories.sdk_repos import SDKInstallationRepository

    repo = SDKInstallationRepository()
    written = 0
    for site_id, site_facts in facts.items():
        try:
            existing = await repo.get(tenant_id, site_id)
            merged = merge_site_install(existing, site_facts, tenant_id)
            await repo.upsert(merged)
            written += 1
        except Exception as exc:
            logger.warning(
                "Install signal projection failed tenant=%s site=%s: %s",
                tenant_id,
                site_id,
                exc,
                exc_info=True,
            )
            metrics.increment(
                "sdk_install_signal_projection_failed_total",
                labels={"tenant_id": tenant_id},
            )

    if written:
        metrics.increment(
            "sdk_install_signals_recorded", value=written, labels={"tenant_id": tenant_id}
        )
    return written


def describe_site_install(record: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The read view of a site's install state.

    Lives beside the write side so the states a record can be in and the states
    a reader can see are declared together — a reader that invented its own
    mapping would go on reporting "live" for a status the writer had renamed.

    ``age_seconds`` is reported rather than thresholded into a state. A site
    installed months ago is still correctly installed: these are one-shot
    install-time signals, not heartbeats, and calling an old success "stale"
    would invent a health problem out of a working integration.
    """
    from shared.common.common import utc_now

    if not record:
        return {
            "state": STATE_AWAITING,
            "status": None,
            "signals": {},
            "signals_observed": [],
            "signals_missing": list(SIGNAL_ORDER),
            "last_signal": None,
            "last_signal_at": None,
            "first_signal_at": None,
            "age_seconds": None,
            "install_mode": None,
            "loader_version": None,
            "sdk_version": None,
            "compatibility_tier": None,
            "desired_version": None,
            "drift_status": None,
            "reason": None,
            "warnings": [],
        }

    signals = record.get("signals") or {}
    last_signal = record.get("last_signal")
    last_at = record.get("last_signal_at") or record.get("last_seen")
    failure = signals.get(SIGNAL_FAILED) or {}

    return {
        "state": _state_of(record),
        "status": record.get("status"),
        "signals": signals,
        "signals_observed": [s for s in SIGNAL_ORDER if s in signals],
        "signals_missing": [s for s in SIGNAL_ORDER if s not in signals],
        "last_signal": last_signal,
        "last_signal_at": last_at,
        "first_signal_at": record.get("first_signal_at"),
        "age_seconds": _age_seconds(last_at, utc_now()),
        "install_mode": record.get("install_mode"),
        "loader_version": record.get("loader_version"),
        "sdk_version": record.get("sdk_version"),
        "compatibility_tier": record.get("compatibility_tier"),
        "desired_version": record.get("desired_version"),
        "drift_status": record.get("drift_status"),
        # Reported from the failure signal only, and only while the failure is
        # still the current state: a fixed site that kept showing last month's
        # error would send operators to debug something that no longer exists.
        "reason": failure.get("reason") if record.get("status") == STATUS_FAILED else None,
        "warnings": failure.get("warnings", []) if record.get("status") == STATUS_FAILED else [],
    }


def _state_of(record: dict[str, Any]) -> str:
    status = record.get("status")
    if status == STATUS_FAILED:
        return STATE_FAILED
    if status == STATUS_LIVE:
        return STATE_LIVE
    return STATE_LOADED


def _age_seconds(occurred_at: Optional[str], now) -> Optional[float]:
    if not occurred_at:
        return None
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return round(max(0.0, (now - parsed).total_seconds()), 2)


def schedule_install_projection(
    tenant_id: str,
    normalized_events: Sequence[dict[str, Any]],
    declared_site: Optional[str] = None,
) -> Optional["asyncio.Task"]:
    """Run ``record_install_signals`` off the request path. Returns the task, or None.

    ``declared_site`` is threaded through from the request rather than read here,
    because the request is gone by the time the task runs — see
    ``record_install_signals`` for what it confines.

    Fire-and-forget, for the same reason identity resolution is: the events are
    already durable in Bronze by the time this is called, so making the tenant's
    request wait on a verifier-side write would trade their ingest latency for
    a dashboard field. A dropped projection is recoverable — the next signal,
    or the read endpoints' ``awaiting_first_signal`` state, still tells the
    truth — whereas a slow batch endpoint is not.

    Fast path: a batch with no install signals allocates no task at all, which
    is every batch except the handful that follow an install.
    """
    if not any(
        n.get("event_type") in INSTALL_SIGNAL_TYPES for n in normalized_events
    ):
        return None

    def _log_task_exc(task: "asyncio.Task", tenant: str = tenant_id) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:  # pragma: no cover - record_install_signals swallows its own
            logger.error("Install projection task failed tenant=%s: %s", tenant, exc)

    task = asyncio.create_task(
        record_install_signals(tenant_id, normalized_events, declared_site)
    )
    task.add_done_callback(_log_task_exc)
    return task
