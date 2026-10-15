"""Bridge between SDK commerce signals and the canonical event plane.

The SDK (web/mobile) emits commerce signals (:class:`SDKCommerceSignal`); the
Universal Provider Runtime emits provider-neutral canonical events
(:class:`AetherEvent <shared.integration_contracts.events.AetherEvent>`) whose
``data`` carries canonical projections such as
:class:`OrderSnapshot <shared.commerce_contracts.order.OrderSnapshot>`. This
module is the typed seam that maps between the two vocabularies:

The canonical S2 contract (mirrored by the TS bridge):

* ``sdk_event_type`` is the BARE SDK signal name (``product_view``,
  ``cart_updated``, ``checkout_started``, ``order_confirmed``) — never
  prefixed with ``commerce.``. The SDK keys on bare names.
* ``canonical_event_type`` is the DOTTED runtime event type
  (``commerce.product.viewed``, ``commerce.order.confirmed``, ...) — exactly
  what ``AetherEvent.event_type`` is.
* The mapping table holds EXACTLY the four semantically-valid pairs;
  ``commerce.order.created`` does NOT map to ``order_confirmed`` (a
  created-but-not-confirmed order must never be reported as confirmed), and
  any unmapped canonical event type PASSES THROUGH (``sdk_event_type`` equals
  ``event_type``).

This module implements:

* :func:`envelope_bridge` — project a canonical :class:`AetherEvent` onto a
  :class:`BridgeResult` in the SDK vocabulary. The mapping is deterministic and
  keyed ONLY off ``event_type`` + the canonical payload; ``provider`` is
  metadata and is never used as a mapping key.
* :func:`payload_bridge` — project an :class:`OrderSnapshot` onto a
  :class:`BridgeResult`. The payload is a JSON-safe canonical OrderSnapshot:
  amounts are exact decimal STRINGS (``model_dump(mode="json")`` semantics) —
  never :class:`decimal.Decimal` objects, never binary floats, so the
  no-float-drift invariant survives the JSON boundary.
* :func:`confirm_interaction` — reconcile an SDK signal against a canonical
  event via ``lineage.source_record_id``. Replay-safe (a second confirm of the
  same signal is ``replay``), and NEVER auto-confirms on a mismatch (a
  non-matching lineage is ``unconfirmed``, a missing canonical is
  ``not_found``). The replay guard is fail-closed: a malformed (non-list)
  ``confirmed_signal_ids`` value is treated as cannot-verify → ``unconfirmed``,
  never ``matched``.

Every result carries ``confirmed`` (true only for a positive match) and a
``confirmation_state`` verdict. All models are closed (``extra="forbid"``) so a
drifted field fails loudly instead of passing through.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from shared.commerce_contracts.order import OrderSnapshot
from shared.integration_contracts.events import AetherEvent

SDK_SIGNAL_SCHEMA_VERSION = "1"

# Context key the ingestion runtime stamps onto a canonical event the first
# time it confirms an SDK signal, so a duplicate SDK delivery of the same
# signal is recognized as a replay rather than double-confirmed.
_CONFIRMED_SIGNAL_IDS_KEY = "confirmed_signal_ids"

# Canonical (dotted runtime) event_type -> BARE SDK signal name. The SDK keys
# on bare names, so the SDK-side event type is NEVER prefixed with ``commerce.``.
# The table holds EXACTLY the four semantically-valid pairs; notably,
# ``commerce.order.created`` is deliberately absent — a created-but-not-confirmed
# order must never be reported as ``order_confirmed`` (false-positive rule).
# Any canonical event type NOT in this table passes through unmapped
# (``sdk_event_type`` = ``event_type``).
_CANONICAL_EVENT_TYPE_TO_SDK: dict[str, str] = {
    "commerce.product.viewed": "product_view",
    "commerce.cart.updated": "cart_updated",
    "commerce.checkout.started": "checkout_started",
    "commerce.order.confirmed": "order_confirmed",
}


class SDKCommerceSignal(BaseModel):
    """A commerce signal emitted by the SDK.

    ``signal_id`` is the SDK's own unique id for the signal (used for replay
    detection). ``lineage`` links the signal back to the source record the
    runtime normalized, e.g. ``{"source_record_id": "..."}``; the value is
    optional so a pre-reconciliation signal can carry no lineage yet.
    """

    model_config = ConfigDict(extra="forbid")

    signal_id: str
    signal_type: Literal[
        "product_view",
        "cart_updated",
        "checkout_started",
        "order_confirmed",
    ]
    occurred_at: str
    source_url: str
    lineage: dict[str, str | None]  # {"source_record_id": str | None}
    payload: dict[str, Any]


class BridgeResult(BaseModel):
    """A commerce signal/event bridged into the SDK vocabulary.

    ``sdk_event_type`` is the BARE SDK signal name (``product_view``,
    ``order_confirmed``, ...) — never prefixed with ``commerce.``;
    ``canonical_event_type`` and ``provider`` are metadata only — ``provider``
    is NEVER a mapping key in ``payload`` or in any bridge mapping.
    ``confirmed`` is true only for a positive ``matched`` confirmation;
    ``confirmation_state`` is one of ``matched`` | ``unconfirmed`` | ``replay``
    | ``not_found``.
    """

    model_config = ConfigDict(extra="forbid")

    sdk_event_type: str
    payload: dict[str, Any]
    canonical_event_type: str  # metadata
    provider: str  # metadata, NEVER a mapping key
    confirmed: bool
    confirmation_state: Literal["matched", "unconfirmed", "replay", "not_found"]


def _signal_to_sdk_event(signal_type: str) -> str:
    """Return the SDK signal's BARE SDK event type.

    ``SDKCommerceSignal.signal_type`` already IS the bare SDK signal name, so
    this is a pass-through — it is never re-prefixed with ``commerce.``.
    """
    return signal_type


def envelope_bridge(event: AetherEvent) -> BridgeResult:
    """Project a canonical :class:`AetherEvent` onto a :class:`BridgeResult`.

    Deterministic: the result is keyed off ``event_type`` + the canonical
    payload ONLY — the ``provider`` / ``provider_identity`` lineage never
    participates in the mapping (``provider`` is copied through as metadata and
    never appears as a payload key). Unmapped canonical event types pass
    through as their own ``sdk_event_type``. Envelope bridging is a projection,
    not a confirmation: ``confirmed=False`` and
    ``confirmation_state="not_found"``.
    """
    return BridgeResult(
        sdk_event_type=_CANONICAL_EVENT_TYPE_TO_SDK.get(event.event_type, event.event_type),
        payload=dict(event.data),
        canonical_event_type=event.event_type,
        provider=event.provider,
        confirmed=False,
        confirmation_state="not_found",
    )


def payload_bridge(snapshot: OrderSnapshot) -> BridgeResult:
    """Project an :class:`OrderSnapshot` onto a :class:`BridgeResult`.

    The payload is the canonical OrderSnapshot emitted with
    ``model_dump(mode="json")`` semantics: ``total.amount`` is an exact decimal
    STRING (never a :class:`decimal.Decimal` object, never a binary float), so
    the no-float-drift invariant survives the JSON boundary. The snapshot
    carries no provider lineage, so ``provider`` is empty metadata. A
    projection, not a confirmation: ``confirmed=False`` and
    ``confirmation_state="not_found"``.
    """
    payload: dict[str, Any] = snapshot.model_dump(mode="json")
    return BridgeResult(
        sdk_event_type="order_confirmed",
        payload=payload,
        canonical_event_type="commerce.order.confirmed",
        provider="",
        confirmed=False,
        confirmation_state="not_found",
    )


def confirm_interaction(signal: SDKCommerceSignal, canonical: AetherEvent | None) -> BridgeResult:
    """Reconcile an SDK signal against a canonical event.

    The reconciliation key is ``signal.lineage["source_record_id"]`` compared
    against ``canonical.source_record_id``. Outcomes:

    * ``matched`` — lineage matches and the signal has not already been
      confirmed against that event (``confirmed=True``);
    * ``replay`` — lineage matches BUT ``signal.signal_id`` already appears in
      ``canonical.context["confirmed_signal_ids"]``. The ingestion runtime
      stamps a confirmed signal id into the canonical event's context on first
      confirm, so a duplicate SDK delivery is recognized as a replay
      (``confirmed=False``);
    * ``unconfirmed`` — the lineage does not match, the signal carries no
      ``source_record_id``, OR ``confirmed_signal_ids`` is present but not a
      well-formed list (a malformed replay stamp cannot be verified — the
      guard fails CLOSED so a duplicate confirm can never fall through to
      ``matched``). The bridge NEVER auto-confirms on a mismatch
      (``confirmed=False``);
    * ``not_found`` — no canonical event was supplied (``canonical is None``).

    The result payload is the SDK signal's own payload (deterministic across
    all outcomes); the reconciliation verdict lives in ``confirmed`` and
    ``confirmation_state``.
    """
    sdk_event_type = _signal_to_sdk_event(signal.signal_type)
    payload = dict(signal.payload)

    if canonical is None:
        return BridgeResult(
            sdk_event_type=sdk_event_type,
            payload=payload,
            canonical_event_type="",
            provider="",
            confirmed=False,
            confirmation_state="not_found",
        )

    source_record_id = signal.lineage.get("source_record_id")
    if not source_record_id or source_record_id != canonical.source_record_id:
        return BridgeResult(
            sdk_event_type=sdk_event_type,
            payload=payload,
            canonical_event_type=canonical.event_type,
            provider=canonical.provider,
            confirmed=False,
            confirmation_state="unconfirmed",
        )

    # Fail-closed replay guard. A key absent from context means this is the
    # FIRST confirm of this signal against this event → matched. A malformed
    # NON-list value (e.g. a stringified list) means the replay state CANNOT be
    # verified → treat it as cannot-verify → unconfirmed, NEVER matched (a
    # duplicate confirm must not fall open to a false matched).
    if _CONFIRMED_SIGNAL_IDS_KEY not in canonical.context:
        return BridgeResult(
            sdk_event_type=sdk_event_type,
            payload=payload,
            canonical_event_type=canonical.event_type,
            provider=canonical.provider,
            confirmed=True,
            confirmation_state="matched",
        )

    confirmed_ids = canonical.context[_CONFIRMED_SIGNAL_IDS_KEY]
    if not isinstance(confirmed_ids, (list, tuple)):
        return BridgeResult(
            sdk_event_type=sdk_event_type,
            payload=payload,
            canonical_event_type=canonical.event_type,
            provider=canonical.provider,
            confirmed=False,
            confirmation_state="unconfirmed",
        )

    if signal.signal_id in confirmed_ids:
        return BridgeResult(
            sdk_event_type=sdk_event_type,
            payload=payload,
            canonical_event_type=canonical.event_type,
            provider=canonical.provider,
            confirmed=False,
            confirmation_state="replay",
        )

    return BridgeResult(
        sdk_event_type=sdk_event_type,
        payload=payload,
        canonical_event_type=canonical.event_type,
        provider=canonical.provider,
        confirmed=True,
        confirmation_state="matched",
    )


__all__ = [
    "SDK_SIGNAL_SCHEMA_VERSION",
    "SDKCommerceSignal",
    "BridgeResult",
    "envelope_bridge",
    "payload_bridge",
    "confirm_interaction",
]
