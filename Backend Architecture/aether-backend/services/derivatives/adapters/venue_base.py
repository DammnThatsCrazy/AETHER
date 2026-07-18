"""Canonical read-only derivatives venue adapter base.

``VenueDerivativesAdapter`` is the ONE canonical object every real venue
(Hyperliquid, dYdX, GMX, Drift) implements. It satisfies the conformance-tested
:class:`~services.derivatives.adapters.base.DerivativesAdapter` interface
(``descriptor`` / ``validate_config`` / ``test_connection`` / ``pull_events``) and
ALSO exposes the transport surface the ``DerivativesConnector`` contract needed —
``fetch_*`` (→ Bronze), ``subscribe_account_stream`` (→ Bronze), ``checkpoint`` —
so the two interfaces converge on a single object. The fixture/import path
(``multi_venue.FixtureVenueAdapter`` + ``connectors.generic_import``) stays a
DISTINCT explicit fallback for partners without credentials — never the venue
path.

Design invariants:
- Observation-only. ``validate_config`` refuses any authority beyond read-only
  and rejects mutating credential scopes; ``execution_by_aether`` is always
  False. There is no order / transfer / withdrawal method anywhere.
- Import-safe + offline by default. The REST client and WS frame source are
  INJECTABLE; with nothing injected the adapter is honestly CREDENTIAL_WAITING
  and ``pull_events`` yields no events (there is nothing to observe without a
  configured client).
- Exact ``Decimal`` arithmetic. Every amount is normalized through
  ``decimal_from_provider`` and emitted as a decimal string; binary floats are
  rejected at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from shared.common.common import utc_now
from services.integrations.connectors.base import ImplementationStatus
from services.derivatives.adapters.base import DerivativesAdapter
from services.derivatives.connectors.base import (
    DerivativesConnectorCheckpoint,
    DerivativesConnectorHealth,
)
from services.derivatives.connectors.stream import (
    FrameSourceFactory,
    ReconnectingStream,
    StreamResult,
)
from services.derivatives.connectors.transport import (
    PROVIDER_HEALTH_NOT_CONFIGURED,
    PROVIDER_HEALTH_OK,
    ProviderRequestError,
    RestBackfillClient,
)
from services.derivatives.foundation import require_read_only_authority
from services.derivatives.models import (
    BronzeObservation,
    NormalizedFillFact,
    decimal_from_provider,
    validate_read_only_scopes,
)

# Keys whose values must never survive into a stored/normalized record.
_SECRET_KEY_TOKENS = (
    "secret",
    "api_key",
    "apikey",
    "api-key",
    "token",
    "password",
    "private_key",
    "privatekey",
    "authorization",
    "bearer",
    "credential",
    "signature",
    "mnemonic",
)


def _is_secret_key(key: str) -> bool:
    text = str(key).lower().replace("-", "_")
    return any(marker.replace("-", "_") in text for marker in _SECRET_KEY_TOKENS)


def sanitize_venue_payload(value: Any) -> Any:
    """Recursively drop secret-like keys from a provider payload."""
    if isinstance(value, dict):
        return {k: sanitize_venue_payload(v) for k, v in value.items() if not _is_secret_key(k)}
    if isinstance(value, (list, tuple)):
        return [sanitize_venue_payload(v) for v in value]
    return value


def _key_gt(candidate: Any, marker: Any) -> bool:
    """True when ``candidate`` is strictly beyond the high-water ``marker``.

    Compares numerically when both parse as numbers (epoch times / ids), else
    lexically (ISO timestamps sort correctly). ``marker`` None => always beyond.
    """
    if marker is None:
        return True
    try:
        return Decimal(str(candidate)) > Decimal(str(marker))
    except (InvalidOperation, ValueError):
        return str(candidate) > str(marker)


@dataclass(frozen=True)
class StreamPlan:
    """One backfill stream (endpoint family) the adapter pulls and projects.

    ``build_request(cursor)`` returns the read-request dict for the next page
    within a sweep (or None to stop); ``extract_page(json)`` returns
    ``(records, next_page_token)`` — an INTRA-sweep pagination token only.
    ``project(record)`` maps one raw record to canonical observation event(s).
    ``record_key(record)`` returns a monotonic high-water key (epoch/id/ISO) used
    to dedupe across sweeps so a resumed pull emits only NEW records; returning
    None marks a snapshot stream that is always (re)emitted. ``scope``
    distinguishes ``public`` read data from ``private_account`` data.
    """

    record_type: str
    build_request: Callable[[Optional[str]], Optional[dict[str, Any]]]
    extract_page: Callable[[Any], tuple[list[dict[str, Any]], Optional[str]]]
    project: Callable[[dict[str, Any]], list[dict[str, Any]]]
    record_key: Callable[[dict[str, Any]], Optional[Any]] = field(
        default=lambda record: None
    )
    scope: str = "public"
    max_pages: int = 50


class VenueDerivativesAdapter(DerivativesAdapter):
    """Base for real read-only venue adapters. Subclasses declare venue config
    and implement ``backfill_plans`` (+ fill normalization / stream config)."""

    # ── DerivativesAdapter descriptor fields (subclasses override) ─────────
    adapter_id: str = ""
    display_name: str = ""
    implementation_status: ImplementationStatus = ImplementationStatus.CREDENTIAL_GATED
    capabilities: tuple[str, ...] = ()
    supported_instrument_types: tuple[str, ...] = ("perpetual_future",)
    authentication_model: str = "api_key_read_only"
    known_limitations: str = ""

    # ── venue configuration ────────────────────────────────────────────────
    venue_id: str = ""
    default_deployment: str = "mainnet"
    rest_base_url: str = ""
    has_websocket: bool = False
    private_account_data: bool = True
    adapter_version: str = "0.1.0"
    fixture_schema_version: str = "1"

    cert_rate_limit_behavior: str = (
        "HTTP 429 classified as rate_limited; honors Retry-After header, else "
        "exponential backoff; bounded retries then degrades provider health"
    )
    cert_retry_policy: str = (
        "exponential backoff (base 0.2s, x2 per attempt), max 3 retries on "
        "429 / 5xx / timeout / network error; honors Retry-After"
    )

    def __init__(
        self,
        *,
        rest_client: Optional[RestBackfillClient] = None,
        http_transport: Any = None,
        stream_factory: Optional[FrameSourceFactory] = None,
        deployment: Optional[str] = None,
        account_ref: Optional[str] = None,
        http_timeout: float = 15.0,
        sleeper: Optional[Callable[[float], Awaitable[Any]]] = None,
        max_retries: int = 3,
        backoff_base: float = 0.2,
        max_pages: int = 50,
    ) -> None:
        self._deployment = deployment or self.default_deployment
        self._account_ref = account_ref
        self._max_pages = max_pages
        self._sleeper = sleeper
        # Per-stream high-water marks for the sweep currently in flight, so a
        # venue's request builder can push the resume mark into the request.
        self._resume: dict[str, Any] = {}
        # A REST client is present when explicitly injected OR when a transport
        # (mock in tests, real in prod) is supplied. Absent => CREDENTIAL_WAITING.
        if rest_client is not None:
            self._rest: Optional[RestBackfillClient] = rest_client
        elif http_transport is not None:
            self._rest = RestBackfillClient(
                http_transport=http_transport,
                base_url=self.rest_base_url,
                http_timeout=http_timeout,
                sleeper=sleeper,
                max_retries=max_retries,
                backoff_base=backoff_base,
            )
        else:
            self._rest = None
        self._stream_factory = stream_factory

    # ── DerivativesAdapter surface ─────────────────────────────────────────
    def validate_config(self, config: dict[str, Any]) -> None:
        """Refuse anything beyond read-only authority AND reject mutating scopes."""
        require_read_only_authority(config.get("authority_type", "read_only"))
        scopes = config.get("scopes")
        if scopes:
            validate_read_only_scopes(list(scopes))

    async def test_connection(self) -> dict[str, Any]:
        """Read-only connectivity probe; never mutates venue state.

        Offline-safe: without a configured client the adapter reports an honest
        credential-waiting state instead of raising.
        """
        if self._rest is None:
            return {
                "ok": False,
                "state": PROVIDER_HEALTH_NOT_CONFIGURED,
                "detail": (
                    f"{self.display_name} is credential-waiting: inject a "
                    "read-only REST client to observe live data."
                ),
                "execution_by_aether": False,
            }
        request = self._connectivity_request()
        health = {"health": PROVIDER_HEALTH_OK}
        try:
            await self._rest.request_json(request, health=health)
        except ProviderRequestError as exc:
            return {
                "ok": False,
                "state": exc.classification,
                "detail": str(exc),
                "execution_by_aether": False,
            }
        return {"ok": True, "state": PROVIDER_HEALTH_OK, "execution_by_aether": False}

    async def pull_events(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Backfill canonical observation events over the injectable REST client.

        Idempotent per checkpoint; cursors advance monotonically and persist in
        the returned checkpoint. Without a configured client, yields no events.
        """
        checkpoint = checkpoint or {}
        cursors: dict[str, Any] = dict(checkpoint.get("cursors") or {})
        if self._rest is None:
            return [], {"cursors": cursors, "provider_health": PROVIDER_HEALTH_NOT_CONFIGURED}

        # Expose stored high-water marks so venue request builders can filter the
        # sweep server-side (efficient resume) where the venue supports it.
        self._resume = dict(cursors)
        health = {"health": PROVIDER_HEALTH_OK}
        events: list[dict[str, Any]] = []
        for plan in self.backfill_plans():
            if plan.scope == "private_account" and not self._account_ref:
                continue
            try:
                records, _ = await self._rest.paginate(
                    plan.build_request,
                    plan.extract_page,
                    start_cursor=None,
                    max_pages=plan.max_pages,
                    health=health,
                )
            except ProviderRequestError as exc:
                health["health"] = exc.classification
                continue
            hwm = cursors.get(plan.record_type)
            max_key = hwm
            for record in records:
                key = plan.record_key(record)
                # Inclusive (at-least-once): emit records at/after the high-water
                # mark so records sharing the boundary key are never dropped;
                # downstream idempotency keys dedupe the re-observed boundary.
                if key is None or hwm is None or not _key_gt(hwm, key):
                    events.extend(plan.project(record))
                if key is not None and _key_gt(key, max_key):
                    max_key = key
            cursors[plan.record_type] = None if max_key is None else str(max_key)
        return events, {"cursors": cursors, "provider_health": health["health"]}

    # ── venue hooks (subclasses implement) ─────────────────────────────────
    def backfill_plans(self) -> list[StreamPlan]:
        """Return the ordered backfill streams for this venue."""
        raise NotImplementedError

    def _connectivity_request(self) -> dict[str, Any]:
        """A read-only request used by ``test_connection``. Override per venue."""
        return {"method": "GET", "url": self.rest_base_url or "/"}

    def normalize_bronze(self, observation: BronzeObservation) -> list[NormalizedFillFact]:
        """Bronze → Silver fill facts (converged ``DerivativesConnector.normalize``).

        Only fill records normalize to Silver facts; other record types project
        straight to canonical events via ``backfill_plans``. Default: nothing.
        """
        return []

    def stream_channel(self) -> str:
        return "account"

    # ── converged DerivativesConnector transport surface ───────────────────
    def _context(self) -> dict[str, Any]:
        return {
            "venue_id": self.venue_id,
            "deployment": self._deployment,
            "account_ref": self._account_ref,
        }

    async def _fetch_bronze(
        self, record_type: str, *, account_ref: Optional[str] = None,
    ) -> list[BronzeObservation]:
        """Run the matching backfill plan and wrap raw records as Bronze."""
        if self._rest is None:
            return []
        account = account_ref or self._account_ref or "public"
        plan = next((p for p in self.backfill_plans() if p.record_type == record_type), None)
        if plan is None:
            return []
        health = {"health": PROVIDER_HEALTH_OK}
        records, _ = await self._rest.paginate(
            plan.build_request, plan.extract_page,
            start_cursor=None, max_pages=plan.max_pages, health=health,
        )
        return [self._bronze(record_type, account, record) for record in records]

    async def fetch_markets(self, *, checkpoint: Any = None) -> list[BronzeObservation]:
        return await self._fetch_bronze("raw_market")

    async def fetch_account_snapshot(
        self, *, account_ref: str, checkpoint: Any = None,
    ) -> list[BronzeObservation]:
        return await self._fetch_bronze("raw_account", account_ref=account_ref)

    async def fetch_fills(
        self, *, account_ref: str, checkpoint: Any = None,
    ) -> list[BronzeObservation]:
        return await self._fetch_bronze("raw_fill", account_ref=account_ref)

    async def subscribe_account_stream(
        self, *, account_ref: str, checkpoint: Any = None,
    ) -> AsyncIterator[BronzeObservation]:
        """Yield Bronze from the injectable WS frame source; empty when none."""
        if self._stream_factory is None:
            return
        resume = checkpoint if isinstance(checkpoint, int) else None
        source = self._stream_factory(resume)
        async for frame in source:
            payload = frame.get("payload") if isinstance(frame, dict) else None
            yield self._bronze(
                "websocket_message", account_ref,
                dict(payload) if isinstance(payload, dict) else dict(frame),
            )

    async def run_stream(
        self, *, resume_cursor: Optional[int] = None, max_reconnects: int = 5,
        market_id: Optional[str] = None,
    ) -> StreamResult:
        """Drive the venue WS feed through gap tracking + bounded reconnect."""
        if self._stream_factory is None:
            return StreamResult(completed=True)
        stream = ReconnectingStream(
            self._stream_factory,
            venue_id=self.venue_id,
            market_id=market_id or f"{self.venue_id}:{self._deployment}:*",
            channel=self.stream_channel(),
            max_reconnects=max_reconnects,
            sleeper=self._sleeper,
        )
        return await stream.run(resume_cursor=resume_cursor)

    def checkpoint(
        self, observations: list[BronzeObservation],
    ) -> Optional[DerivativesConnectorCheckpoint]:
        if not observations:
            return None
        latest = max(observations, key=lambda obs: obs.observed_at)
        return DerivativesConnectorCheckpoint(
            tenant_id=latest.tenant_id,
            connector_id=self.venue_id,
            checkpoint_value=f"{latest.record_type}:{latest.source_record_id}:{latest.observed_at}",
            advanced_at=utc_now().isoformat(),
        )

    def provider_health(self, state: str = PROVIDER_HEALTH_OK) -> DerivativesConnectorHealth:
        return DerivativesConnectorHealth(connector_id=self.venue_id, state=state)

    def _bronze(
        self, record_type: str, account_ref: str, payload: dict[str, Any],
    ) -> BronzeObservation:
        source_id = str(
            payload.get("id")
            or payload.get("hash")
            or payload.get("tid")
            or payload.get("fill_id")
            or utc_now().isoformat()
        )
        return BronzeObservation(
            tenant_id="public",
            provider=self.venue_id,
            deployment=self._deployment,
            record_type=record_type,
            source_record_id=source_id,
            raw_payload=sanitize_venue_payload(payload),
            observed_at=str(payload.get("time") or payload.get("observed_at") or utc_now().isoformat()),
            idempotency_key=":".join(
                [self.venue_id, self._deployment, account_ref, record_type, source_id]
            ),
        )

    # ── canonical event construction helpers ───────────────────────────────
    def canonical_market_id(self, market: str) -> str:
        return f"{self.venue_id}:{self._deployment}:{market}"

    def event(
        self,
        event_name: str,
        market: str,
        *,
        trading_account_id: Optional[str] = None,
        **payload: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "venue_id": self.venue_id,
            "canonical_market_id": self.canonical_market_id(market),
        }
        if trading_account_id is not None:
            body["trading_account_id"] = trading_account_id
        body.update(payload)
        return {"event_name": event_name, "payload": body, "execution_by_aether": False}

    @staticmethod
    def amount(value: Any, field: str) -> str:
        """Normalize a provider amount to an exact decimal string (rejects float)."""
        return str(decimal_from_provider(value, field))

    # ── certification hooks (shared.certification.checks probes these) ──────
    def certification_descriptor(self) -> Any:
        from shared.certification.descriptor import AdapterCertificationDescriptor
        from shared.certification.readiness import CredentialReadiness

        return AdapterCertificationDescriptor(
            provider=self.venue_id,
            domain="derivatives",
            adapter=type(self).__name__,
            adapter_version=self.adapter_version,
            supported_operations=list(self.capabilities),
            unsupported_operations=[],
            required_credentials=["read_only_api_key"],
            required_endpoints=[self.rest_base_url] if self.rest_base_url else [],
            pagination_model="cursor",
            streaming_model="websocket" if self.has_websocket else "polling",
            rate_limit_behavior=self.cert_rate_limit_behavior,
            retry_policy=self.cert_retry_policy,
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version=self.fixture_schema_version,
            first_release=True,
        )

    def sanitize_payload(self, payload: Any) -> Any:
        return sanitize_venue_payload(payload)

    def build_request(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Sample read-request construction with credential injection seam."""
        headers: dict[str, str] = {}
        credential = ctx.get("credential") if isinstance(ctx, dict) else None
        secret = None
        if isinstance(credential, dict):
            secret = credential.get("api_key") or credential.get("secret")
        elif isinstance(credential, str):
            secret = credential
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return {
            "method": "GET",
            "url": self.rest_base_url or f"/{self.venue_id}",
            "headers": headers,
            "params": {},
        }

    def advance_cursor(self, cursor: Any) -> str:
        """Move an opaque cursor forward (cursor-persistence certification)."""
        try:
            return str(int(cursor) + 1)
        except (TypeError, ValueError):
            return f"{cursor}:next"

    def dedupe_key(self, event: Any) -> tuple:
        if isinstance(event, dict):
            payload = event.get("payload", event)
            ident = (
                payload.get("fill_id")
                or payload.get("funding_payment_id")
                or payload.get("trading_fee_id")
                or payload.get("position_id")
                or payload.get("margin_snapshot_id")
                or payload.get("order_id")
                or event.get("id")
            )
            return (event.get("event_name"), str(ident))
        return (repr(event),)

    def sequence_of(self, event: Any) -> tuple:
        if isinstance(event, dict):
            payload = event.get("payload", event)
            return (
                str(payload.get("executed_at") or payload.get("settled_at") or payload.get("observed_at") or event.get("seq") or ""),
                str(payload.get("fill_id") or event.get("id") or ""),
            )
        return (str(event),)

    def normalize(self, record: Any) -> Optional[dict[str, Any]]:
        """Certification hook: raw record → stable canonical projection.

        Idempotent for identical input; tolerant of drift/malformed input
        (returns None rather than crashing).
        """
        if not isinstance(record, dict):
            return None
        try:
            events = self._certify_project(record)
        except (ValueError, KeyError, TypeError, AttributeError):
            return None
        if not events:
            return None
        return events[0].get("payload")

    def _certify_project(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        """Project a raw record via the first backfill plan (for certification)."""
        plans = self.backfill_plans()
        for plan in plans:
            try:
                events = plan.project(record)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if events:
                return events
        return []

    def health(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        ctx = context or {}
        if not ctx.get("configured"):
            return {"healthy": False, "state": PROVIDER_HEALTH_NOT_CONFIGURED}
        state = ctx.get("provider_health") or PROVIDER_HEALTH_OK
        return {"healthy": state == PROVIDER_HEALTH_OK, "state": state}


__all__ = ["StreamPlan", "VenueDerivativesAdapter", "sanitize_venue_payload"]
