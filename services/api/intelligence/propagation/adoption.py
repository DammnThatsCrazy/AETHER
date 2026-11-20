"""Adoption events from read-only venue fills of tenant-linked accounts.

Adoption = a subject's **first** position in an instrument, on the side it
opened. Fills are replayed per ``(account, canonical_market_id)`` through the
shared derivatives position engine; the first epoch that opens from flat is
the candidate. Across all of a subject's linked accounts and markets, only the
earliest candidate per instrument counts. Adding to a held position, later
re-entries, and closes never produce an adoption.

Instrument and side:

* Perpetuals: instrument = ``canonical_market_id``; side = ``long`` / ``short``.
* Event contracts: instrument = ``event_contract_ref`` (the condition); side =
  the outcome bought. Two outcome tokens of one condition are one instrument.

Fills from accounts without an active tenant link are ignored: the tenant only
sees its own linked users.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable, Mapping

from intelligence.propagation.contracts import AdoptionEvent
from value.derivatives.models import (
    DerivativesValidationError,
    NormalizedFillFact,
    OrderSide,
    PositionStatus,
)
from value.derivatives.position_engine import apply_fill


def _instant(value: str):
    """Parsed instant for chronological comparison; unparseable sorts last."""
    from datetime import datetime, timezone

    from shared.temporal.instant import try_parse_instant

    parsed, _ = try_parse_instant(value)
    return parsed or datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def _account_ref(trading_account_id: str) -> str:
    return trading_account_id[5:] if trading_account_id.startswith("acct_") else trading_account_id


def _fill_fact(tenant_id: str, venue: str, payload: Mapping[str, Any]) -> NormalizedFillFact:
    return NormalizedFillFact(
        tenant_id=tenant_id,
        provider=venue,
        deployment=str(payload.get("deployment") or "mainnet"),
        trading_account_id=str(payload["trading_account_id"]),
        canonical_market_id=str(payload["canonical_market_id"]),
        fill_id=str(payload["fill_id"]),
        side=OrderSide(str(payload["side"]).lower()),
        price=Decimal(str(payload["price"])),
        quantity=Decimal(str(payload["quantity"])),
        executed_at=str(payload["executed_at"]),
    )


def _history_truncated(fact: NormalizedFillFact, payload: Mapping[str, Any]) -> bool:
    direction = str(payload.get("direction") or "").lower()
    if direction and not direction.startswith("open"):
        return True
    # Event contracts have no short side: a first observed sell means the
    # outcome tokens were acquired before the observed history.
    return payload.get("instrument_type") == "event_contract" and fact.side is OrderSide.SELL


def adoptions_from_fill_events(
    tenant_id: str,
    events: Iterable[Mapping[str, Any]],
    subjects_by_account: Mapping[tuple[str, str], str],
) -> tuple[list[AdoptionEvent], set[str]]:
    """Derive first-entry adoptions from canonical ``derivatives_fill_observed`` events.

    ``subjects_by_account`` maps ``(venue, account_ref)`` to the tenant subject
    (from active venue account links). Returns ``(adoptions, reason_codes)``.
    """
    reasons: set[str] = set()
    by_stream: dict[tuple[str, str, str], list[tuple[NormalizedFillFact, Mapping[str, Any]]]] = defaultdict(list)
    for event in events:
        if event.get("event_name") != "derivatives_fill_observed":
            continue
        payload = event.get("payload") or {}
        venue = str(payload.get("venue_id") or "")
        account = _account_ref(str(payload.get("trading_account_id") or ""))
        subject = subjects_by_account.get((venue, account.lower())) or subjects_by_account.get((venue, account))
        if subject is None:
            reasons.add("fill_account_not_linked")
            continue
        try:
            fact = _fill_fact(tenant_id, venue, payload)
        except (KeyError, ValueError, ArithmeticError, DerivativesValidationError):
            reasons.add("fill_unparseable")
            continue
        by_stream[(subject, venue, fact.canonical_market_id + "|" + fact.trading_account_id)].append((fact, payload))

    candidates: dict[tuple[str, str], AdoptionEvent] = {}
    for (subject, venue, _stream), items in sorted(by_stream.items()):
        items.sort(key=lambda pair: (_instant(pair[0].executed_at), pair[0].fill_id))
        if _history_truncated(items[0][0], items[0][1]):
            # The earliest observed fill acts on a position opened before the
            # observed history, so this subject is not a first-time entrant.
            reasons.add("fill_history_truncated")
            continue
        state = None
        for fact, payload in items:
            epochs = apply_fill(state, fact)
            opened = [
                e for e in epochs
                if e.status is PositionStatus.OPEN and e.opened_at == fact.executed_at
                and fact.fill_id in e.source_fill_ids and len(e.source_fill_ids) == 1
            ]
            state = epochs[-1]
            if not opened:
                continue
            epoch = opened[0]
            instrument_key = str(payload.get("event_contract_ref") or fact.canonical_market_id)
            if payload.get("instrument_type") == "event_contract":
                side = str(payload.get("outcome") or "")
                if not side:
                    reasons.add("event_contract_outcome_missing")
                    break
            else:
                side = epoch.side.value
            adoption = AdoptionEvent(
                tenant_id=tenant_id,
                subject_id=subject,
                instrument_key=instrument_key,
                side=side,
                adopted_at=fact.executed_at,
                venue=venue,
                account_ref=_account_ref(fact.trading_account_id),
                canonical_market_id=fact.canonical_market_id,
                evidence_refs=(f"{venue}:fill:{fact.fill_id}",),
            )
            key = (subject, instrument_key)
            current = candidates.get(key)
            if current is None or (_instant(adoption.adopted_at), adoption.canonical_market_id) < (
                _instant(current.adopted_at), current.canonical_market_id,
            ):
                candidates[key] = adoption
            break  # only the first opening epoch of each stream can be a first entry
    return sorted(candidates.values(), key=lambda a: (_instant(a.adopted_at), a.subject_id)), reasons


__all__ = ["adoptions_from_fill_events"]
