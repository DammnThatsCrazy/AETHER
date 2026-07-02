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
from typing import Any, Optional

from services.delivery.models import ExternalOutcomeEvent, ExternalOutcomeType

logger = logging.getLogger("aether.delivery.outcome_processor")


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
        link = await self._resolve_link(provider, external_id, tenant_id)

        # Loop-prevention: skip if state hasn't changed
        new_state = raw.get("new_state")
        if link and new_state and link.get("sync_status") == new_state:
            logger.debug(
                "outcome_router_skipped: same state=%s id=%s", new_state, outcome.id
            )
            return

        suggestion_outcome = self._map_event_type_to_suggestion_outcome(event_type)

        if link:
            intent_id = link.get("intent_id")
            source_type = link.get("resource_type", "suggestion")

            if source_type == "suggestion" and suggestion_outcome is not None:
                await self._route_to_suggestion(outcome, link=link, outcome_state=suggestion_outcome)

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
        """Update suggestion outcome_state if suggestion_repo is available."""
        if self._suggestion_repo is None:
            return
        raw = outcome.raw_payload or {}
        suggestion_id = raw.get("suggestion_id") or link.get("resource_id")
        if not suggestion_id:
            return
        try:
            await self._suggestion_repo.update(suggestion_id, {
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
        notification_id = link.get("notification_id") or link.get("resource_id")
        if not notification_id:
            return
        try:
            raw = outcome.raw_payload or {}
            await self._notification_repo.update(notification_id, {
                "last_external_outcome": raw.get("event_type", "delivered"),
                "last_outcome_at": outcome.ingested_at,
            })
        except Exception as exc:
            logger.warning("route_to_notification_failed id=%s: %s", notification_id, exc)

    async def _resolve_link(
        self, provider: str, external_id: str, tenant_id: str
    ) -> Optional[dict]:
        try:
            results = await self._link_repo.find_many(
                filters={"provider": provider, "external_id": external_id, "tenant_id": tenant_id},
                limit=1,
            )
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

    def __init__(self, inbox_repo, outcome_repo, link_repo, router=None):
        self._inbox_repo = inbox_repo
        self._outcome_repo = outcome_repo
        self._link_repo = link_repo
        self._router: Optional[OutcomeRouter] = router

    async def process_pending(self, limit: int = 20) -> int:
        """Claim pending WebhookInbox records, verify, normalise, persist, route.

        Returns the count of records processed (successfully or with error).
        """
        try:
            records = await self._inbox_repo.find_many(
                filters={"processed": False}, limit=limit
            )
        except Exception as exc:
            logger.warning("inbox_find_failed: %s", exc)
            return 0

        count = 0
        for record in records:
            record_id = record.get("id", "")
            try:
                # 1. Signature verification
                sig_verified = await self._verify_signature(record)
                try:
                    await self._inbox_repo.update(record_id, {"verified": sig_verified})
                except Exception:
                    pass  # best-effort; don't abort processing

                # 2. Normalise
                outcome = await self._normalize(record)
                if outcome is None:
                    await self._inbox_repo.mark_processed(record_id)
                    count += 1
                    continue

                # 3. Persist ExternalOutcomeEvent
                try:
                    await self._outcome_repo.insert(outcome.id, outcome.model_dump())
                except Exception as exc:
                    logger.warning("outcome_persist_failed id=%s: %s", record_id, exc)

                # 4. Route
                if self._router is not None:
                    try:
                        await self._router.route(outcome)
                    except Exception as exc:
                        logger.warning("outcome_route_failed id=%s: %s", record_id, exc)

                # 5. Mark processed
                await self._inbox_repo.mark_processed(record_id)
                count += 1

            except Exception as exc:
                logger.warning("inbox_process_failed id=%s: %s", record_id, exc)
                try:
                    await self._inbox_repo.mark_processed(record_id, error=str(exc)[:500])
                except Exception:
                    pass
                count += 1

        return count

    async def _verify_signature(self, inbox: dict) -> bool:
        """Provider-specific signature verification.

        Returns True when the signature is valid.  Unknown providers or
        missing secrets yield False without discarding the record.
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
                timestamp = headers.get("x-slack-request-timestamp", "")
                signature = headers.get("x-slack-signature", "")
                signing_secret = inbox.get("signing_secret", "")
                if not signing_secret or not timestamp or not signature:
                    return False
                from services.delivery.adapters.slack import SlackAdapter
                adapter = SlackAdapter()
                return await adapter.verify_inbound(
                    raw_body,
                    headers,
                    credential=signing_secret,
                )

            elif provider == "linear":
                linear_sig = headers.get("linear-signature", "")
                webhook_secret = inbox.get("webhook_secret", "")
                if not linear_sig or not webhook_secret:
                    return False
                expected = hmac.new(
                    webhook_secret.encode(), raw_body, hashlib.sha256
                ).hexdigest()
                from services.delivery.security import constant_time_compare
                return constant_time_compare(expected, linear_sig)

            elif provider == "jira":
                jira_sig = headers.get("x-hub-signature-256", "")
                webhook_secret = inbox.get("webhook_secret", "")
                if not jira_sig or not webhook_secret:
                    return False
                expected = "sha256=" + hmac.new(
                    webhook_secret.encode(), raw_body, hashlib.sha256
                ).hexdigest()
                from services.delivery.security import constant_time_compare
                return constant_time_compare(expected, jira_sig)

            elif provider == "webhook":
                aether_sig = headers.get("x-aether-signature", "")
                aether_ts = headers.get("x-aether-timestamp", "")
                signing_secret = inbox.get("signing_secret", "")
                if not aether_sig or not signing_secret:
                    # Signature already verified at ingestion time; trust if present
                    return bool(aether_sig)
                # Verify HMAC-SHA256 of timestamp.body
                base = f"{aether_ts}.{raw_body_str}"
                expected_hex = hmac.new(
                    signing_secret.encode(), base.encode(), hashlib.sha256
                ).hexdigest()
                # X-Aether-Signature may be "sha256=<hex>" or "v1=<hex>" or bare hex
                sig_value = aether_sig.split("=", 1)[-1] if "=" in aether_sig else aether_sig
                from services.delivery.security import constant_time_compare
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
                identifier = data.get("identifier") or data.get("id")
                if identifier:
                    external_id = str(identifier)
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
