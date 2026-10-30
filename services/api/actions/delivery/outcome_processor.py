"""Webhook inbox processor and outcome router for the delivery closed-loop pipeline.

WebhookInboxProcessor
---------------------
Runs as a background task.  On each tick it claims unprocessed WebhookInbox
records, verifies provider signatures, normalises raw payloads into
ExternalOutcomeEvent, persists them, and hands off to OutcomeRouter.

OutcomeRouter
-------------
Resolves the ExternalResourceLink, applies loop-prevention guards, maps the
outcome event type to an Aether object state, and updates suggestions /
notification lifecycle accordingly.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

from actions.delivery.models import ExternalOutcomeEvent, ExternalOutcomeType
from shared.logger.logger import metrics

logger = logging.getLogger("aether.delivery.outcome_processor")

# Providers whose callbacks are routed only to the tenant of the stored
# ExternalResourceLink (and its receipt/job) the delivery resolves to.
_BOUND_PROVIDERS = frozenset({"linear", "jira", "webhook"})
_MAX_LINK_CANDIDATES = 20
_CALLBACK_REPLAY_WINDOW_SECONDS = 300
_LINEAR_REPLAY_WINDOW_SECONDS = 60


# ─── OutcomeRouter ───────────────────────────────────────────────────────────

class OutcomeRouter:
    """Routes a normalised ExternalOutcomeEvent to the correct Aether domain object."""

    def __init__(
        self,
        outcome_repo,
        link_repo,
        suggestion_repo=None,
        notification_repo=None,
        producer=None,
    ):
        self._outcome_repo = outcome_repo
        self._link_repo = link_repo
        self._suggestion_repo = suggestion_repo
        self._notification_repo = notification_repo
        self._producer = producer

    async def route(self, outcome: ExternalOutcomeEvent) -> None:
        """Resolve aether object → route to suggestion or notification → emit graph edge → mark routed."""
        raw = outcome.raw_payload or {}

        # Loop-prevention: skip events that originated inside Aether
        if raw.get("aether_origin"):
            logger.debug("outcome_router_skipped: aether_origin=True id=%s", outcome.id)
            return

        event_type: str = raw.get("event_type", "delivered")
        external_id = outcome.external_id
        tenant_id = outcome.tenant_id
        provider = outcome.provider

        # Resolve ExternalResourceLink
        link = await self._resolve_link(provider, external_id, tenant_id, outcome.receipt_id)

        # Loop-prevention: skip if state hasn't changed
        new_state = raw.get("new_state")
        if link and new_state and link.get("sync_status") == new_state:
            logger.debug(
                "outcome_router_skipped: same state=%s id=%s", new_state, outcome.id
            )
            return

        suggestion_outcome = self._map_event_type_to_suggestion_outcome(event_type)

        if link:
            target_type, _ = _link_target(link)
            if target_type == "suggestion" and suggestion_outcome is not None:
                await self._route_to_suggestion(outcome, link=link, outcome_state=suggestion_outcome)
            elif target_type == "notification":
                await self._route_to_notification(outcome, link=link)

        # Mark outcome as routed in raw_payload (persisted via update)
        try:
            updated_payload = {**raw, "routed": True}
            if link:
                updated_payload["routed_to_intent_id"] = link.get("intent_id")
            await self._outcome_repo.update(outcome.id, {"raw_payload": updated_payload})
        except Exception as exc:
            logger.warning("outcome_mark_routed_failed id=%s: %s", outcome.id, exc)

    def _map_event_type_to_suggestion_outcome(self, event_type: str) -> Optional[str]:
        """Map OutcomeEventType string → suggestion outcome_state.

        Returns None when the event should be recorded but not change state.
        """
        _map = {
            "acknowledged": "executed",
            "accepted": "executed",
            "resolved": "executed",
            "rejected": "rejected",
            "cancelled": "rejected",
            "status_changed": "in_progress",
        }
        return _map.get(event_type)  # commented/assigned → None (record only)

    async def _route_to_suggestion(
        self, outcome: ExternalOutcomeEvent, *, link: dict, outcome_state: str
    ) -> None:
        """Update the linked suggestion's outcome_state.

        The target is only ever the link's own resource: the link was resolved
        within the webhook's tenant, and ``patch`` re-checks that tenant. Ids
        carried in the provider payload are never trusted.
        """
        if self._suggestion_repo is None:
            return
        target_type, suggestion_id = _link_target(link)
        if target_type != "suggestion" or not suggestion_id:
            return
        try:
            await self._suggestion_repo.patch(suggestion_id, outcome.tenant_id, {
                "outcome_state": outcome_state,
                "last_outcome_event_id": outcome.id,
            })
            logger.info(
                "suggestion_outcome_updated id=%s state=%s",
                suggestion_id, outcome_state,
            )
        except Exception as exc:
            logger.warning("route_to_suggestion_failed id=%s: %s", suggestion_id, exc)

    async def _route_to_notification(
        self, outcome: ExternalOutcomeEvent, *, link: dict
    ) -> None:
        """Advance notification lifecycle if notification_repo is available."""
        if self._notification_repo is None:
            return
        target_type, notification_id = _link_target(link)
        if target_type != "notification" or not notification_id:
            return
        try:
            row = await self._notification_repo.find_by_id(notification_id)
            if row is None or row.get("tenant_id") != outcome.tenant_id:
                logger.warning(
                    "route_to_notification_skipped id=%s: not in tenant %s",
                    notification_id, outcome.tenant_id,
                )
                return
            raw = outcome.raw_payload or {}
            # The notification table has no outcome columns; operator_context
            # is its JSONB bag for this kind of annotation.
            await self._notification_repo.update(notification_id, {
                "operator_context": {
                    **(row.get("operator_context") or {}),
                    "last_external_outcome": raw.get("event_type", "delivered"),
                    "last_outcome_at": outcome.ingested_at,
                },
            })
        except Exception as exc:
            logger.warning("route_to_notification_failed id=%s: %s", notification_id, exc)

    async def _resolve_link(
        self, provider: str, external_id: str, tenant_id: str, receipt_id: Optional[str] = None
    ) -> Optional[dict]:
        filters = {"provider": provider, "external_id": external_id, "tenant_id": tenant_id}
        if receipt_id:
            filters["receipt_id"] = receipt_id
        try:
            results = await self._link_repo.find_many(filters=filters, limit=1)
            return results[0] if results else None
        except Exception as exc:
            logger.warning("resolve_link_failed provider=%s ext_id=%s: %s", provider, external_id, exc)
            return None


# ─── WebhookInboxProcessor ───────────────────────────────────────────────────

class WebhookInboxProcessor:
    """Processes pending WebhookInbox records asynchronously.

    Typical lifecycle per record:
    1. Verify provider-native signature.
    2. Normalise raw body → ExternalOutcomeEvent.
    3. Persist the normalised event.
    4. Hand off to OutcomeRouter.
    5. Mark record as processed.
    """

    def __init__(
        self,
        inbox_repo,
        outcome_repo,
        link_repo,
        router=None,
        *,
        receipt_repo=None,
        job_repo=None,
        secret_resolver: Optional[Callable[[dict], Awaitable[Optional[str]]]] = None,
    ):
        self._inbox_repo = inbox_repo
        self._outcome_repo = outcome_repo
        self._link_repo = link_repo
        self._router: Optional[OutcomeRouter] = router
        self._receipt_repo = receipt_repo
        self._job_repo = job_repo
        self._secret_resolver = secret_resolver

    async def process_pending(self, limit: int = 20) -> int:
        """Claim pending WebhookInbox records, verify, normalise, persist, route.

        Returns the count of records attempted.

        Zero Silent Failure (program sec7): a record is marked processed ONLY on
        a terminal disposition — signature unverified, or nothing to normalise.
        A persist or routing failure is RETRYABLE: the record's claim is
        released (``processing=False``, ``processed=False``) so the next tick
        re-queues it instead of silently dropping the hand-off.
        """
        try:
            records = await self._inbox_repo.claim_pending(limit=limit)
        except Exception as exc:
            logger.warning("inbox_claim_pending_failed: %s", exc)
            return 0

        count = 0
        for record in records:
            record_id = record.get("id", "")
            try:
                # 0. Resolve the stored delivery this callback refers to. The
                #    tenant comes only from that binding; a lookup failure is
                #    retryable, an unmatched delivery is terminal.
                binding = await self._bind(record)
                if record.get("provider") in _BOUND_PROVIDERS and binding is None:
                    logger.warning(
                        "inbox_delivery_unbound id=%s provider=%s — skipping routing",
                        record_id, record.get("provider"),
                    )
                    await self._dead_letter(record, "unbound_delivery")
                    count += 1
                    continue

                # 1. Signature verification
                sig_verified = await self._verify_signature(
                    record, secret=(binding or {}).get("secret")
                )
                try:
                    await self._inbox_repo.update(record_id, {"verified": sig_verified})
                except Exception:
                    pass  # best-effort status update

                # Reject unverified records — do not route forged payloads.
                # Terminal: retrying cannot change the signature result, so the
                # record is dead-lettered with an error rather than re-queued.
                if not sig_verified:
                    logger.warning(
                        "inbox_signature_unverified id=%s provider=%s — skipping routing",
                        record_id, record.get("provider"),
                    )
                    await self._dead_letter(record, "signature_unverified")
                    count += 1
                    continue

                # 2. Normalise
                outcome = await self._normalize(record)
                if outcome is None:
                    # Nothing to process (e.g. URL verification challenge) — terminal.
                    await self._inbox_repo.mark_processed(record_id)
                    count += 1
                    continue
                if binding is not None:
                    link = binding["link"]
                    binding_update = {
                        "tenant_id": link["tenant_id"],
                        "intent_id": link.get("intent_id"),
                        "receipt_id": link.get("receipt_id"),
                    }
                    if binding.get("verified_receipt_binding") is True:
                        binding_update.update({
                            "producer_provenance": "verified_callback",
                            "signature_authority": (
                            "tenant_owned_webhook_signature"
                            if record.get("provider") == "webhook"
                            else "external_provider_signature"
                            ),
                        })
                    outcome = outcome.model_copy(update=binding_update)

                # 3. Persist ExternalOutcomeEvent. A failure here must NOT mark the
                #    record processed — it will be retried on the next tick.
                await self._outcome_repo.insert(outcome.id, outcome.model_dump())

                # 4. Route. A routing/publish failure is likewise RETRYABLE — the
                #    outcome is already persisted, but the hand-off failed, so the
                #    inbox record is re-queued (never marked processed) instead of
                #    losing the delivery silently.
                if self._router is not None:
                    await self._router.route(outcome)

                # 5. Mark processed (only reached on full success)
                await self._inbox_repo.mark_processed(record_id)
                count += 1

            except Exception as exc:
                # Persist or route failure: release the claim for retry. Do NOT
                # mark processed — that would silently drop the outcome.
                logger.warning("inbox_process_failed id=%s: %s", record_id, exc)
                try:
                    await self._inbox_repo.update(
                        record_id, {"processing": False, "processed": False}
                    )
                except Exception:
                    pass
                count += 1

        return count

    async def _dead_letter(self, record: dict, reason: str) -> None:
        await self._inbox_repo.mark_processed(record.get("id", ""), error=reason)
        metrics.increment("delivery_inbox_dead_lettered_total", labels={
            "provider": record.get("provider") or "unknown", "reason": reason,
        })

    async def _verify_signature(self, inbox: dict, *, secret: Optional[str] = None) -> bool:
        """Provider-specific signature verification.

        Returns True when the signature is valid.  Unknown providers or
        missing secrets yield False without discarding the record. ``secret``
        is the bound channel's secret for Aether delivery callbacks.
        """
        provider = inbox.get("provider", "")
        headers: dict = {k.lower(): v for k, v in (inbox.get("headers") or {}).items()}

        raw_body_str = inbox.get("raw_body", "") or ""
        try:
            raw_body: bytes = raw_body_str.encode("utf-8")
        except Exception:
            raw_body = b""

        try:
            if provider == "slack":
                import os as _os

                timestamp = headers.get("x-slack-request-timestamp", "")
                signature = headers.get("x-slack-signature", "")
                signing_secret = inbox.get("signing_secret", "") or _os.getenv(
                    "SLACK_SIGNING_SECRET", ""
                )
                if not signing_secret or not timestamp or not signature:
                    return False
                from actions.delivery.adapters.slack import SlackAdapter
                adapter = SlackAdapter()
                return await adapter.verify_inbound(
                    raw_body,
                    headers,
                    credential=signing_secret,
                )

            elif provider == "linear":
                from config.settings import settings as _settings

                linear_sig = headers.get("linear-signature", "")
                # Inbox rows never carry the secret (that would persist
                # plaintext at rest) — resolve from configuration.
                webhook_secret = inbox.get("webhook_secret", "") or (
                    _settings.delivery.linear_webhook_secret
                )
                if not linear_sig or not webhook_secret:
                    return False
                expected = hmac.new(
                    webhook_secret.encode(), raw_body, hashlib.sha256
                ).hexdigest()
                from actions.delivery.security import constant_time_compare
                if not constant_time_compare(expected, linear_sig):
                    return False
                try:
                    sent_at = float(json.loads(raw_body_str)["webhookTimestamp"]) / 1000
                except (KeyError, TypeError, ValueError):
                    return False
                return _within_window(sent_at, inbox, _LINEAR_REPLAY_WINDOW_SECONDS)

            elif provider == "jira":
                from config.settings import settings as _settings

                jira_sig = headers.get("x-hub-signature-256", "")
                webhook_secret = inbox.get("webhook_secret", "") or (
                    _settings.delivery.jira_webhook_secret
                )
                if not jira_sig or not webhook_secret:
                    return False
                expected = "sha256=" + hmac.new(
                    webhook_secret.encode(), raw_body, hashlib.sha256
                ).hexdigest()
                from actions.delivery.security import constant_time_compare
                return constant_time_compare(expected, jira_sig)

            elif provider == "webhook":
                aether_sig = headers.get("x-aether-signature", "")
                aether_ts = headers.get("x-aether-timestamp", "")
                signing_secret = secret
                # Signature, timestamp and the bound channel's secret are all
                # required — a platform-wide secret never verifies a callback.
                if not aether_sig or not aether_ts or not signing_secret:
                    return False
                from actions.delivery.security import constant_time_compare
                try:
                    sent_at = float(aether_ts)
                except ValueError:
                    return False
                if not _within_window(sent_at, inbox, _CALLBACK_REPLAY_WINDOW_SECONDS):
                    logger.warning("webhook_callback_timestamp_stale inbox_id=%s", inbox.get("id"))
                    return False
                # Verify HMAC-SHA256 of timestamp.body
                base = f"{aether_ts}.{raw_body_str}"
                expected_hex = hmac.new(
                    signing_secret.encode(), base.encode(), hashlib.sha256
                ).hexdigest()
                # X-Aether-Signature may be "sha256=<hex>" or "v1=<hex>" or bare hex
                sig_value = aether_sig.split("=", 1)[-1] if "=" in aether_sig else aether_sig
                return constant_time_compare(expected_hex, sig_value)

            else:
                # Unknown provider: mark unverified but continue processing
                return False

        except Exception as exc:
            logger.warning("signature_verify_failed provider=%s: %s", provider, exc)
            return False

    async def _normalize(self, inbox: dict) -> Optional[ExternalOutcomeEvent]:
        """Normalise inbox record into ExternalOutcomeEvent per provider.

        Returns None when the record should be silently skipped (e.g. URL
        verification challenges that require no outcome event).
        """
        provider = inbox.get("provider", "")
        tenant_id = inbox.get("tenant_id", "")
        raw_body_str = inbox.get("raw_body", "") or ""

        # Parse body
        try:
            # Handle URL-encoded Slack payloads
            if provider == "slack" and raw_body_str.startswith("payload="):
                import urllib.parse
                payload: dict = json.loads(urllib.parse.unquote(raw_body_str[8:]))
            else:
                payload = json.loads(raw_body_str) if raw_body_str else {}
        except (json.JSONDecodeError, Exception):
            payload = {}

        event_type = "delivered"
        external_id: str = inbox.get("id", "")
        actor_external_id: Optional[str] = None
        actor_display_name: Optional[str] = None
        new_state: Optional[str] = None
        extra_meta: dict[str, Any] = {}

        try:
            if provider == "slack":
                payload_type = payload.get("type", "")
                # Slack URL verification challenge — skip, no outcome event needed
                if payload_type == "url_verification":
                    return None
                if payload_type in ("interactive_message", "block_actions"):
                    event_type = "acknowledged"
                user = payload.get("user") or {}
                actor_external_id = user.get("id", "") or None
                actor_display_name = user.get("username", "") or None
                actions = payload.get("actions") or []
                if actions:
                    action_id = actions[0].get("action_id", "")
                    parts = action_id.split(":")
                    if len(parts) >= 3:
                        extra_meta["action_type"] = parts[0]
                        extra_meta["suggestion_id"] = parts[1]
                        extra_meta["action_tenant_id"] = parts[2]
                        if parts[1]:
                            # Use suggestion_id as external_id for link resolution
                            external_id = parts[1]
                extra_meta["payload_type"] = payload_type

            elif provider == "linear":
                action = payload.get("action", "update")
                data = payload.get("data") or {}
                if action == "remove":
                    event_type = "cancelled"
                else:
                    state_obj = data.get("state") or {}
                    state_name = state_obj.get("name")
                    if state_name:
                        event_type = "status_changed"
                        new_state = state_name
                    else:
                        event_type = "status_changed"
                # Use UUID (data.id) for link lookup — matches what LinearAdapter stores in receipt
                # Include human-readable identifier in meta only
                uuid_id = data.get("id")
                if uuid_id:
                    external_id = str(uuid_id)
                identifier = data.get("identifier")
                if identifier:
                    extra_meta["linear_identifier"] = identifier
                extra_meta["linear_action"] = action

            elif provider == "jira":
                webhook_event = payload.get("webhookEvent", "")
                if webhook_event == "jira:issue_updated":
                    event_type = "status_changed"
                elif webhook_event == "jira:issue_deleted":
                    event_type = "cancelled"
                elif webhook_event == "comment_created":
                    event_type = "commented"
                issue = payload.get("issue") or {}
                issue_key = issue.get("key")
                if issue_key:
                    external_id = issue_key
                user_info = payload.get("user") or {}
                actor_display_name = user_info.get("displayName") or None
                extra_meta["webhook_event"] = webhook_event

            else:
                # Generic webhook / Aether callback
                event_data = payload.get("event_data") or payload
                event_type = event_data.get("event_type", "delivered")
                delivery_id = _delivery_id(payload)
                if delivery_id:
                    external_id = delivery_id
                extra_meta.update(
                    {k: v for k, v in event_data.items() if k != "event_type"}
                )

        except Exception as exc:
            logger.warning("normalize_failed provider=%s inbox_id=%s: %s", provider, inbox.get("id"), exc)
            return None

        # Map string event_type → ExternalOutcomeType enum
        _type_map: dict[str, ExternalOutcomeType] = {
            "delivered": ExternalOutcomeType.DELIVERED,
            "acknowledged": ExternalOutcomeType.RESOLVED,
            "accepted": ExternalOutcomeType.RESOLVED,
            "resolved": ExternalOutcomeType.RESOLVED,
            "rejected": ExternalOutcomeType.FAILED,
            "cancelled": ExternalOutcomeType.FAILED,
            "status_changed": ExternalOutcomeType.OPENED,
            "in_progress": ExternalOutcomeType.OPENED,
            "commented": ExternalOutcomeType.REPLIED,
            "replied": ExternalOutcomeType.REPLIED,
            "assigned": ExternalOutcomeType.OPENED,
            "opened": ExternalOutcomeType.OPENED,
            "clicked": ExternalOutcomeType.CLICKED,
            "bounced": ExternalOutcomeType.BOUNCED,
        }
        outcome_type = _type_map.get(event_type, ExternalOutcomeType.DELIVERED)

        # Build enriched raw_payload for the outcome event
        raw_payload: dict[str, Any] = {
            **payload,
            "event_type": event_type,
            "provider": provider,
            "inbox_id": inbox.get("id"),
        }
        if actor_external_id:
            raw_payload["actor_external_id"] = actor_external_id
        if actor_display_name:
            raw_payload["actor_display_name"] = actor_display_name
        if new_state:
            raw_payload["new_state"] = new_state
        raw_payload.update(extra_meta)

        return ExternalOutcomeEvent(
            tenant_id=tenant_id,
            provider=provider,
            external_id=external_id,
            outcome_type=outcome_type,
            raw_payload=raw_payload,
        )

    async def _bind(self, inbox: dict) -> Optional[dict]:
        """Resolve the one stored delivery this callback refers to.

        Returns ``{"link": ..., "secret": ...}`` or ``None`` when the callback
        matches no delivery, or deliveries in more than one tenant. Nothing the
        sender chose (headers, query, body tenant ids) is consulted.
        """
        provider = inbox.get("provider", "")
        if provider not in _BOUND_PROVIDERS:
            return None
        try:
            payload = json.loads(inbox.get("raw_body") or "")
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if provider == "linear":
            key = (payload.get("data") or {}).get("id")
        elif provider == "jira":
            key = (payload.get("issue") or {}).get("key")
        else:
            key = _delivery_id(payload)
        if not key:
            return None

        links = await self._link_repo.find_many(
            filters={"provider": provider, "external_id": str(key)},
            limit=_MAX_LINK_CANDIDATES,
        )
        matches: list[dict] = []
        for link in links:
            if (not link.get("tenant_id") or link.get("provider") != provider
                    or link.get("external_id") != str(key)):
                continue
            stored = await self._stored_delivery(link)
            if stored is None:
                continue
            receipt, job = stored
            # Keep legacy callback routing behavior, but grant trusted event
            # provenance only for the complete canonical receipt binding.
            verified_receipt_binding = bool(
                receipt and job
                and receipt.get("id") == link.get("receipt_id")
                and receipt.get("tenant_id") == link.get("tenant_id")
                and receipt.get("intent_id") == link.get("intent_id")
                and isinstance(receipt.get("delivered_at"), str)
                and receipt.get("provider_adapter") == provider
                and receipt.get("external_id") == link.get("external_id")
                and job.get("id") == receipt.get("job_id")
                and job.get("tenant_id") == link.get("tenant_id")
                and job.get("intent_id") == link.get("intent_id")
                and job.get("provider_adapter") == provider
            )
            secret = None
            if provider == "jira" and not _jira_site_matches(payload, receipt, job):
                continue
            if provider == "linear" and not _linear_scope_matches(payload, receipt, job):
                continue
            if provider == "webhook":
                if not job:
                    continue
                secret = await self._resolve_secret(job)
                if not secret:
                    continue
            matches.append({"link": link, "secret": secret,
                            "verified_receipt_binding": verified_receipt_binding})
        if len({m["link"]["tenant_id"] for m in matches}) != 1:
            return None
        return matches[0]

    async def _stored_delivery(self, link: dict) -> Optional[tuple[dict, dict]]:
        """The link's receipt and job (``{}`` when not stored); ``None`` when
        either belongs to a tenant other than the link's."""
        tenant_id = link["tenant_id"]
        receipt: dict = {}
        job: dict = {}
        if link.get("receipt_id"):
            receipt = await self._receipts().find_by_id(link["receipt_id"]) or {}
        if receipt and receipt.get("job_id"):
            job = await self._jobs().find_by_id(receipt["job_id"]) or {}
        if (receipt and receipt.get("tenant_id") != tenant_id) or (
            job and job.get("tenant_id") != tenant_id
        ):
            return None
        return receipt, job

    def _receipts(self):
        if self._receipt_repo is None:
            from repositories.delivery_repos import ProviderReceiptRepository
            self._receipt_repo = ProviderReceiptRepository()
        return self._receipt_repo

    def _jobs(self):
        if self._job_repo is None:
            from repositories.delivery_repos import DeliveryJobRepository
            self._job_repo = DeliveryJobRepository()
        return self._job_repo

    async def _resolve_secret(self, job: dict) -> Optional[str]:
        if self._secret_resolver is None:
            from actions.delivery.worker import resolve_job_credential
            self._secret_resolver = resolve_job_credential
        return await self._secret_resolver(job)

    async def _resolve_external_link(
        self, external_system: str, external_id: str, tenant_id: str
    ) -> Optional[dict]:
        """Look up ExternalResourceLink by (external_system, external_id, tenant_id)."""
        try:
            results = await self._link_repo.find_many(
                filters={
                    "provider": external_system,
                    "external_id": external_id,
                    "tenant_id": tenant_id,
                },
                limit=1,
            )
            return results[0] if results else None
        except Exception as exc:
            logger.warning(
                "resolve_external_link_failed system=%s ext_id=%s: %s",
                external_system, external_id, exc,
            )
            return None

    async def run(self) -> None:
        """Background loop: process_pending() every 5s, sleep if none pending."""
        logger.info("WebhookInboxProcessor started")
        while True:
            try:
                processed = await self.process_pending()
                if processed == 0:
                    await asyncio.sleep(5.0)
                # If we processed a full batch, loop immediately to drain
            except asyncio.CancelledError:
                logger.info("WebhookInboxProcessor shutting down")
                break
            except Exception as exc:
                logger.warning("inbox_processor_loop_error: %s", exc)
                await asyncio.sleep(5.0)


# ─── Binding helpers ─────────────────────────────────────────────────────────

def _link_target(link: dict) -> tuple[str, str]:
    """``(object type, object id)`` the delivery link was written for.

    Links stored before the ``aether_object_*`` fields existed carry the
    legacy ``notification_id`` or ``resource_type``/``resource_id`` keys.
    """
    if link.get("aether_object_type") and link.get("aether_object_id"):
        return link["aether_object_type"], link["aether_object_id"]
    if link.get("notification_id"):
        return "notification", link["notification_id"]
    return link.get("resource_type", "suggestion"), link.get("resource_id") or ""


def _delivery_id(payload: dict) -> str:
    event_data = payload.get("event_data")
    if not isinstance(event_data, dict):
        event_data = payload
    return str(event_data.get("delivery_id") or payload.get("delivery_id") or "")


def _host(url: Any) -> Optional[str]:
    if not isinstance(url, str) or not url:
        return None
    return (urlparse(url).hostname or "").lower() or None


def _jira_site_matches(payload: dict, receipt: dict, job: dict) -> bool:
    """Issue keys repeat across Jira sites; the event's ``issue.self`` host
    must be the site the bound job created the issue on."""
    host = _host((payload.get("issue") or {}).get("self"))
    config = job.get("provider_config") or {}
    bound = {
        _host((receipt.get("raw_response") or {}).get("self")),
        _host(config.get("base_url") or config.get("site_url")),
    } - {None}
    return host is not None and host in bound


def _linear_scope_matches(payload: dict, receipt: dict, job: dict) -> bool:
    """The event must come from the bound delivery's organisation when one was
    stored (an issue may since have moved to another team in it); otherwise
    from its stored team."""
    issue = (
        ((receipt.get("raw_response") or {}).get("data") or {}).get("issueCreate") or {}
    ).get("issue") or {}
    team = issue.get("team") or {}
    stored_org = (team.get("organization") or {}).get("id")
    if stored_org:
        return payload.get("organizationId") == stored_org
    stored_team = team.get("id") or (job.get("provider_config") or {}).get("team_id")
    data = payload.get("data") or {}
    if stored_team and (data.get("teamId") or (data.get("team") or {}).get("id")) != stored_team:
        return False
    return True


def _within_window(sent_at: float, inbox: dict, window_seconds: int) -> bool:
    """Compare the sender's timestamp with when the route received the
    callback, so a processing backlog never rejects a fresh delivery. Rows
    stored before ``received_at`` was recorded fall back to ``created_at``."""
    try:
        stamp = inbox.get("received_at") or inbox["created_at"]
        received_at = datetime.fromisoformat(str(stamp)).timestamp()
    except (KeyError, TypeError, ValueError):
        received_at = time.time()
    return abs(received_at - sent_at) <= window_seconds
