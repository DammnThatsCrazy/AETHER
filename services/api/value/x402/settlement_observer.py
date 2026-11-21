"""x402 settlement observer — on-chain proof for payments a tenant's server saw.

Aether is observation-only (ADR-012). It never issues a 402 challenge, approves
a spend or grants access. When a tenant's own server sees an x402 exchange it
reports the parsed headers through ``POST /v1/x402/capture``. If the report
carries a payment proof (transaction hash and payer), this module checks the
chain and records what it found:

* ``settled``  — a final, successful transfer from the payer to the recipient
  of at least the required amount. Emits ``COMMERCE_SETTLEMENT_COMPLETED``.
* ``failed``   — a terminal negative verdict (reverted, payer mismatch,
  amount below the requirement, no matching transfer, malformed hash). Emits
  ``COMMERCE_SETTLEMENT_FAILED``.
* ``pending``  — not final yet, or the RPC was unreachable. Nothing terminal
  is recorded; reporting the same payment again re-checks the chain.
* ``not_observable`` — no proof in the report, or an asset/chain Aether cannot
  verify. No settlement claim is made either way.
* ``conflicting`` — the transaction already has a verified receipt, but this
  report's terms (payer, recipient, amount, asset, chain) differ from what was
  verified. Nothing is recorded or emitted for the conflicting report; the
  earlier verified settlement stands.

The report itself is a source claim; only the chain decides settlement. Agent
references in the report stay as reported (``agent_ref_source``) and are not
resolved here. The observation identity is deterministic per
(tenant, chain, transaction hash), so a repeated report is idempotent.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from .commerce_models import PaymentAuthorization
from .models import CapturedX402Transaction
from .verification import (
    VerificationEngine,
    get_verification_engine,
    is_terminal_verdict,
    is_verifiable,
)

logger = get_logger("aether.service.x402.settlement_observer")

OBSERVER_SOURCE = "x402.settlement_observer"

SETTLED = "settled"
FAILED = "failed"
PENDING = "pending"
NOT_OBSERVABLE = "not_observable"
CONFLICTING = "conflicting"


def observation_id_for(tenant_id: str, chain: str, tx_hash: str) -> str:
    """Deterministic identity for one observed on-chain payment."""
    raw = f"{tenant_id}|{chain}|{tx_hash.strip().lower()}"
    return "x402obs_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def resolve_x402_environment(tenant_id: str) -> str:
    """Credential environment for verification, resolved server-side.

    Reads the tenant's persisted x402 capability state: PARTNER_LIVE uses the
    ``live`` RPC credential, everything else ``sandbox``. A reporter can never
    choose the environment.
    """
    try:
        from tenancy.capabilities.lifecycle import get_lifecycle_authority

        state = await get_lifecycle_authority().get_state(tenant_id, "x402", "live", "commerce")
        if state and state.get("readiness_state") == "partner_live":
            return "live"
    except Exception:  # noqa: BLE001 — default to the safe environment
        pass
    return "sandbox"


async def observe_settlement(
    tenant_id: str,
    tx: CapturedX402Transaction,
    *,
    engine: Optional[VerificationEngine] = None,
    producer: Optional[EventProducer] = None,
) -> dict[str, Any]:
    """Verify one reported x402 payment on-chain and record what the chain says."""
    proof = tx.proof
    if proof is None or not str(proof.tx_hash or "").strip() or not str(proof.payer or "").strip():
        metrics.increment("x402_settlement_observations_total", labels={"state": NOT_OBSERVABLE})
        return {"state": NOT_OBSERVABLE, "reason": "no_payment_proof"}

    chain = tx.terms.chain
    if not is_verifiable(tx.terms.token, chain):
        metrics.increment("x402_settlement_observations_total", labels={"state": NOT_OBSERVABLE})
        return {"state": NOT_OBSERVABLE, "reason": "unsupported_asset_or_chain",
                "asset_symbol": tx.terms.token, "chain": chain}
    tx_hash = proof.tx_hash.strip()
    observation_id = observation_id_for(tenant_id, chain, tx_hash)
    environment = await resolve_x402_environment(tenant_id)
    observed = PaymentAuthorization(
        authorization_id=observation_id,
        tenant_id=tenant_id,
        challenge_id=observation_id,
        approval_id="not_applicable:observed",
        payment_identifier=observation_id,
        amount_usd=tx.terms.amount,
        asset_symbol=tx.terms.token,
        chain=chain,
        environment=environment,
        recipient=tx.terms.recipient,
        payer=proof.payer,
        facilitator_id="not_applicable:observed",
    )
    verifier = engine or get_verification_engine()
    receipt = await verifier.verify(tenant_id, observed, tx_hash, prefer_facilitator=False)
    verdict = receipt.verification_verdict or ("verified" if receipt.verified else "unknown")

    # Every report of one transaction shares an observation id, and the
    # verifier keeps (and returns) an earlier verified receipt when a later
    # re-check fails. A verified receipt therefore only settles this report if
    # it verified exactly these terms; otherwise the report conflicts with what
    # the chain already established and nothing is recorded for it.
    if receipt.verified and not _receipt_matches(receipt, observed):
        state = CONFLICTING
        verdict = "conflicting_report"
    elif receipt.verified:
        state = SETTLED
    elif is_terminal_verdict(verdict):
        state = FAILED
    else:
        state = PENDING

    result: dict[str, Any] = {
        "state": state,
        "observation_id": observation_id,
        "receipt_id": receipt.receipt_id,
        "verdict": verdict,
        "chain": chain,
        "tx_hash": tx_hash,
        "environment": environment,
    }
    metrics.increment("x402_settlement_observations_total", labels={"state": state})

    if state in (SETTLED, FAILED):
        await _emit(
            producer,
            Topic.COMMERCE_SETTLEMENT_COMPLETED if state == SETTLED else Topic.COMMERCE_SETTLEMENT_FAILED,
            tenant_id,
            {
                "observation_id": observation_id,
                "receipt_id": receipt.receipt_id,
                "verdict": verdict,
                "tx_hash": tx_hash,
                "chain": chain,
                # Settled facts carry the verified receipt's terms, never the
                # report's; a failed verdict describes the terms it rejected.
                "asset_symbol": receipt.asset_symbol if state == SETTLED else tx.terms.token,
                "amount": str(receipt.amount_usd if state == SETTLED else tx.terms.amount),
                "payer": receipt.payer if state == SETTLED else proof.payer,
                "recipient": receipt.recipient if state == SETTLED else tx.terms.recipient,
                "verified_at": receipt.verified_at,
                "agent_id": tx.payer_agent_id,
                "agent_ref_source": "capture_reported",
                "payee_service_id": tx.payee_service_id,
                "resource_url": tx.request_url,
            },
        )
    return result


def _receipt_matches(receipt: Any, observed: PaymentAuthorization) -> bool:
    """True when a verified receipt verified exactly the reported terms."""
    def _norm(value: Any) -> str:
        return str(value or "").strip().lower()

    def _addr(value: Any) -> str:
        # EVM hex addresses are case-insensitive; base58 (Solana) is not.
        text = str(value or "").strip()
        return text.lower() if text.lower().startswith("0x") else text

    try:
        same_amount = Decimal(str(receipt.amount_usd)) == Decimal(str(observed.amount_usd))
    except (InvalidOperation, ValueError):
        return False
    return (
        same_amount
        and _addr(receipt.payer) == _addr(observed.payer)
        and _addr(receipt.recipient) == _addr(observed.recipient)
        and _norm(receipt.asset_symbol) == _norm(observed.asset_symbol)
        and _norm(receipt.chain) == _norm(observed.chain)
    )


async def _emit(
    producer: Optional[EventProducer], topic: Topic, tenant_id: str, payload: dict[str, Any]
) -> None:
    try:
        await (producer or EventProducer()).publish(
            Event(topic=topic, payload=payload, tenant_id=tenant_id, source_service=OBSERVER_SOURCE)
        )
    except Exception as exc:  # noqa: BLE001 — the receipt is already durable
        logger.error(f"failed to emit {topic}: {exc}")


__all__ = [
    "CONFLICTING",
    "FAILED",
    "NOT_OBSERVABLE",
    "OBSERVER_SOURCE",
    "PENDING",
    "SETTLED",
    "observation_id_for",
    "observe_settlement",
    "resolve_x402_environment",
]
