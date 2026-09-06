"""Reconciled Control Plane — §19 source-authority + §9.1/§9.2 engine (Phase 3).

§19: Aether must assume multiple sources can describe the same real-world event
or state. **Transport idempotency is not semantic deduplication.** The control
plane's responsibility is to define SourceAuthorityRules (§9.1), define
ObservationEquivalenceKeys (§9.2), configure candidate grouping, preserve
source evidence, and route conflicts into resolution.

This engine supplies *precedence resolution* and *equivalence grouping* for the
control plane's own reasoning (multi-source reconcile, source-authority drift
classification). It never writes canonical downstream outcomes: canonical
identity / outcome / economic-fact / relationship truth belongs to the
downstream resolution/outcome subsystem (§9.3 boundary) — nothing here mints a
canonical fact.

Two verbs (plus private helpers):

* :func:`apply_precedence` — resolve one ``(domain, property_path)`` claim from
  multiple source observations using the applicable §9.1 rule (authority is
  domain/property specific — never a blanket "provider X is always superior").
* :func:`equivalence_group` — group observations by semantic-equivalence key
  (§9.2): equal ``key_components`` after normalization. The group never discards
  evidence — every original observation survives inside a group.

Tenancy is CP-11 enforced at every repo read: tenant-scoped calls see
tenant-or-global rules/keys; a tenant's private configuration never leaks
cross-tenant, and tenant configuration is preferred over global configuration
only in :func:`equivalence_group` scope selection (a tenant equivalence key
shadows a global one for that tenant — the same shadowing rule that repository
reads apply, resolved deterministically rather than by silent preference).
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from services.managed_integrations.source_authority_repository import (
    get_observation_equivalence_key_repository,
    get_source_authority_rule_repository,
)
from shared.temporal.instant import coerce_utc_lenient

# Normalization rules supported by §9.2 equivalence keys. Applied in listed
# order, string values only:
#   "lower"            -> str.lower()
#   "trim"             -> strip leading/trailing whitespace
#   "strip_whitespace" -> remove ALL whitespace characters
_SUPPORTED_NORMALIZATION_RULES: tuple[str, ...] = (
    "lower",
    "strip_whitespace",
    "trim",
)

# Oldest-anchor for observations without an ``observed_at``: untimed evidence
# sorts behind any timed evidence of the same source (never preferred over it).
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    """Lenient instant parse that assumes UTC for naive input. Delegated to the
    temporal kernel — ``coerce_utc_lenient`` is the sanctioned home of the
    assume-UTC-on-naive policy (temporal-integrity gate)."""
    if raw is None or isinstance(raw, bool):
        return None
    return coerce_utc_lenient(raw)


def _obs_instant(observed_at: Any) -> datetime:
    return _parse_ts(observed_at) or _EPOCH


# ── §9.1 precedence resolution ───────────────────────────────────────────────


async def apply_precedence(
    observations: list[dict],
    *,
    domain: str,
    property_path: str,
    tenant_id: Optional[str] = None,
) -> dict:
    """Resolve one claim from multiple source observations (§9.1).

    Each observation is ``{"source": str, "value": Any,
    "observed_at": Optional[str]}``. The applicable rule is the §9.1 rule whose
    ``property_path`` equals the requested path or is its longest matching
    dotted prefix (a rule for ``"order.lifecycle_state"`` beats one for
    ``"order"``); a rule outside its ``valid_from``/``valid_to`` window does
    not apply. Multiple rules at the same specificity raise ValueError (§9.1
    ambiguity) — never a silent preference.

    The resolved value is the first source in ``source_precedence`` that is
    present in the observations — first-in-precedence wins even if a later
    source observed more recently; among several observations of the winning
    source the newest ``observed_at`` wins (an untimed observation sorts
    oldest, so it never beats timed evidence; ties keep input order).

    Returns, when a rule resolves: ``{"resolved_value", "resolved_source",
    "rule_id", "sources_considered", "conflict_strategy"}`` where
    ``sources_considered`` lists the distinct observed sources in precedence
    order (then any remaining observed sources in first-seen order). With no
    applicable rule, or no observed source present in the precedence, returns
    ``{"resolved": False, "conflict": True, "reason": str}`` — the conflict is
    surfaced for resolution, never fabricated away.
    """
    if not isinstance(observations, list):
        raise ValueError("apply_precedence requires an observations list (§9.1)")
    for obs in observations:
        if not isinstance(obs, dict) or "source" not in obs or "value" not in obs:
            raise ValueError(
                "each observation must be a dict carrying 'source' and 'value' "
                "(§9.1; observed_at is optional)"
            )

    now = datetime.now(timezone.utc)
    rules = await get_source_authority_rule_repository().list(domain=domain, tenant_id=tenant_id)

    def _applicable(rule: dict) -> bool:
        valid_from = _parse_ts(rule.get("valid_from"))
        valid_to = _parse_ts(rule.get("valid_to"))
        if valid_from is not None and valid_from > now:
            return False
        if valid_to is not None and valid_to < now:
            return False
        path = rule.get("property_path") or ""
        return property_path == path or property_path.startswith(path + ".")

    matches = [r for r in rules if _applicable(r)]
    if not matches:
        return {
            "resolved": False,
            "conflict": True,
            "reason": (
                f"no applicable §9.1 source-authority rule for domain="
                f"{domain!r} property_path={property_path!r}"
            ),
        }

    # Most specific wins: the longest matching dotted property_path. Two
    # matching rules of equal length can only share the identical path —
    # governance must resolve that duplication, the engine never prefers one.
    longest = max(len(r.get("property_path") or "") for r in matches)
    most_specific = [r for r in matches if len(r.get("property_path") or "") == longest]
    if len(most_specific) > 1:
        ids = ", ".join(sorted(r.get("rule_id") or "?" for r in most_specific))
        raise ValueError(
            f"duplicate §9.1 source-authority rules for domain={domain!r} "
            f"property_path={property_path!r} at equal specificity "
            f"(rule_ids: {ids}) — ambiguity must be resolved by governance, "
            "never silently preferred"
        )

    rule = most_specific[0]
    precedence: list[str] = rule.get("source_precedence") or []

    observed_sources: list[str] = []
    seen: set[str] = set()
    for obs in observations:
        source = obs.get("source")
        if source not in seen:
            seen.add(source)
            observed_sources.append(source)

    resolved_obs: Optional[dict] = None
    resolved_source: Optional[str] = None
    for source in precedence:
        candidates = [obs for obs in observations if obs.get("source") == source]
        if not candidates:
            continue
        resolved_source = source
        # Newest evidence of the winning source wins; untimed evidence sorts
        # oldest (epoch anchor); stable sort keeps input order on ties.
        candidates.sort(key=lambda obs: _obs_instant(obs.get("observed_at")), reverse=True)
        resolved_obs = candidates[0]
        break

    if resolved_obs is None:
        return {
            "resolved": False,
            "conflict": True,
            "reason": (
                f"no observed source appears in §9.1 source_precedence for "
                f"rule {rule.get('rule_id')!r} (precedence: {list(precedence)}; "
                f"observed: {observed_sources})"
            ),
        }

    precedence_set = set(precedence)
    sources_considered = [source for source in precedence if source in seen] + [
        source for source in observed_sources if source not in precedence_set
    ]
    return {
        "resolved_value": resolved_obs.get("value"),
        "resolved_source": resolved_source,
        "rule_id": rule.get("rule_id"),
        "sources_considered": sources_considered,
        "conflict_strategy": rule.get("conflict_strategy"),
    }


# ── §9.2 semantic-equivalence grouping ───────────────────────────────────────


async def equivalence_group(
    observations: list[dict],
    *,
    domain: str,
    tenant_id: Optional[str] = None,
) -> dict:
    """Group observations by the §9.2 semantic-equivalence key for ``domain``.

    Each observation is ``{"source": str, "key_components": {name: value},
    ...}``. The governing key is the tenant's own key for the domain when one
    exists, otherwise the global key (tenant configuration shadows global for
    that tenant, CP-11); several candidate keys at the same scope raise
    ValueError (§9.2 ambiguity — never a silent preference). Observations whose
    ``key_components`` values are equal after normalization (rules applied in
    listed order, string values only) group together; a component the
    observation does not carry is never equal to a carried value — and absence
    of the component is not equivalence between two observations that both
    lack it (missing evidence never fabricates a match, §19).

    With no key row configured for the domain, every observation is grouped
    alone and ``unmatched_domain`` is True — transport idempotency is not
    semantic deduplication (§19), so the engine surfaces the gap instead of
    inventing an equivalence.

    Returns ``{"groups": list[list[dict]], "unmatched_domain": bool,
    "warning": Optional[str]}``. Groups and members keep input order; the
    original observation dicts are preserved untouched — grouping never
    discards source evidence. The key row's ``window`` / ``candidate_types`` /
    ``semantic_dedupe_policy`` are downstream-resolution metadata (§9.2) and do
    not constrain grouping here.
    """
    if not isinstance(observations, list):
        raise ValueError("equivalence_group requires an observations list (§9.2)")
    for obs in observations:
        if (
            not isinstance(obs, dict)
            or "source" not in obs
            or "key_components" not in obs
            or not isinstance(obs.get("key_components"), dict)
        ):
            raise ValueError(
                "each observation must be a dict carrying 'source' and a "
                "'key_components' mapping of component name -> value (§9.2)"
            )

    rows = await get_observation_equivalence_key_repository().list(
        domain=domain, tenant_id=tenant_id
    )
    if not rows:
        warning = (
            f"no §9.2 observation-equivalence key configured for domain="
            f"{domain!r} — every observation grouped alone (transport "
            "idempotency is not semantic deduplication, §19)"
        )
        return {
            "groups": [[obs] for obs in observations],
            "unmatched_domain": True,
            "warning": warning,
        }

    # Scope selection: tenant rows shadow global rows for that tenant; within
    # the chosen scope more than one candidate is an ambiguity (§9.2).
    tenant_rows = (
        [r for r in rows if r.get("tenant_id") == tenant_id] if tenant_id is not None else []
    )
    scoped = tenant_rows if tenant_rows else rows
    if len(scoped) > 1:
        ids = ", ".join(sorted(r.get("key_id") or "?" for r in scoped))
        raise ValueError(
            f"ambiguous §9.2 observation-equivalence keys for domain="
            f"{domain!r} (key_ids: {ids}) — one key per domain per scope "
            "must be chosen by governance, never silently preferred"
        )

    key = scoped[0]
    components: list[str] = list(key.get("key_components") or [])
    normalization: list[str] = list(key.get("normalization_rules") or [])
    if not components:
        raise ValueError(
            f"§9.2 equivalence key {key.get('key_id')!r} for domain="
            f"{domain!r} declares no key_components — a key with nothing to "
            "compare cannot group observations"
        )
    unknown = [r for r in normalization if r not in _SUPPORTED_NORMALIZATION_RULES]
    if unknown:
        raise ValueError(
            f"unsupported §9.2 normalization rule {unknown[0]!r} on key "
            f"{key.get('key_id')!r} (supported: "
            f"{', '.join(_SUPPORTED_NORMALIZATION_RULES)})"
        )

    groups: dict[tuple, list[dict]] = {}
    group_order: list[tuple] = []
    for obs in observations:
        group_key = _group_key(obs, components, normalization)
        if group_key not in groups:
            groups[group_key] = []
            group_order.append(group_key)
        groups[group_key].append(obs)

    return {
        "groups": [groups[gk] for gk in group_order],
        "unmatched_domain": False,
        "warning": None,
    }


def _group_key(obs: dict, components: list[str], normalization: list[str]) -> tuple:
    """One hashable tuple per observation: component values in key order,
    normalized, presence-sensitive, and hashable-safe for grouping.

    Every missing component yields a fresh token, so two observations that
    both lack a component never collide on that position."""
    key_components = obs.get("key_components") or {}
    parts: list[Any] = []
    for name in components:
        if name in key_components:
            parts.append(_hashable_part(_normalize(key_components[name], normalization)))
        else:
            parts.append(object())  # unique absence token, never equal to a value
    return tuple(parts)


def _normalize(value: Any, rules: list[str]) -> Any:
    """Apply §9.2 normalization rules in listed order to string values only."""
    if not isinstance(value, str):
        return value
    for rule in rules:
        if rule == "lower":
            value = value.lower()
        elif rule == "trim":
            value = value.strip()
        elif rule == "strip_whitespace":
            value = "".join(value.split())
    return value


def _hashable_part(value: Any) -> Any:
    """Unhashable component values (dicts/lists) become deterministic JSON
    strings so grouping equality is structural, never identity."""
    try:
        hash(value)
    except TypeError:
        return _json.dumps(value, sort_keys=True, default=str)
    return value
