"""DSR erasure for discovered patterns (component ``pattern_discovery``).

Patterns are derived, rebuildable records, but they *name* entities: the
affected-entity list, evidence details (outlier member lists, motif examples,
co-implicated refs) and review history may hold a subject's identifiers. The
plane:

* finds every tenant pattern whose affected entities, evidence, signature,
  title or summary contain a subject ref (``user:<id>``, ``anon:<id>``,
  ``entity:<id>``, ``agent:<ref>`` or the bare id);
* redacts the subject from the record (affected entities, counts, evidence
  details, signature content, title and summary text, review history and
  promotion outcomes) and re-derives the evidence fingerprint; the signature
  hash, and so the pattern id, is kept;
* deletes the pattern when fewer than two affected entities remain: a pattern
  about one remaining entity would re-identify the erased one by difference;
* deletes run records listing the pattern, because they enumerate pattern ids
  whose membership has changed;
* honours legal holds on ``discovered_patterns`` for any subject ref (the
  whole plane is skipped, never half-applied).

Baselines and feedback rows carry no subject key (aggregate rates and
pattern-id verdicts) and are untouched. Erased entities can re-enter a
pattern only through new evidence, which the ingestion erasure fence already
blocks.
"""
from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.pattern_discovery.erasure")

COMPONENT = "pattern_discovery"
ERASED = "[erased]"
_PAGE = 500
_ENTITY_KINDS = ("user", "anon", "entity", "agent", "session")


def subject_keys(refs: frozenset[str] | set[str]) -> set[str]:
    keys = set(refs)
    for ref in refs:
        for kind in _ENTITY_KINDS:
            keys.add(f"{kind}:{ref}")
    return keys


def _scrub(value: Any, keys: set[str]) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        out = {}
        for k, v in value.items():
            nv, c = _scrub(v, keys)
            out[k] = nv
            changed |= c
        return out, changed
    if isinstance(value, list):
        changed = False
        out_list = []
        for v in value:
            if isinstance(v, str) and v in keys:
                changed = True
                continue  # drop the ref from lists entirely
            if isinstance(v, dict) and (v.get("entity") in keys or v.get("key") in keys):
                changed = True
                continue
            nv, c = _scrub(v, keys)
            out_list.append(nv)
            changed |= c
        return out_list, changed
    if isinstance(value, str) and value in keys:
        return ERASED, True
    return value, False


def _text_names(text: Any, keys: set[str]) -> bool:
    return isinstance(text, str) and any(k in text for k in keys if ":" in k)


def _scrub_text(text: Any, keys: set[str]) -> Any:
    if not isinstance(text, str):
        return text
    for k in sorted((k for k in keys if ":" in k), key=len, reverse=True):
        text = text.replace(k, ERASED)
    return text


def names_subject(row: dict[str, Any], keys: set[str]) -> bool:
    if set(row.get("affected_entity_keys") or []) & keys:
        return True
    if _text_names(row.get("title"), keys) or _text_names(row.get("summary"), keys):
        return True
    _, changed = _scrub({"evidence": row.get("evidence"), "competing": row.get("competing_explanations"),
                         "signature": row.get("signature")}, keys)
    return changed


def redact(row: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    from .registry import evidence_fingerprint

    out = dict(row)
    remaining = [k for k in row.get("affected_entity_keys") or [] if k not in keys]
    removed = len(row.get("affected_entity_keys") or []) - len(remaining)
    out["affected_entity_keys"] = remaining
    out["affected_entities"] = [e for e in row.get("affected_entities") or [] if e.get("key") not in keys]
    out["affected_entity_count"] = max(0, int(row.get("affected_entity_count") or 0) - removed)
    out["entity_kinds"] = sorted({k.split(":", 1)[0] for k in remaining})
    out["evidence"], _ = _scrub(row.get("evidence") or [], keys)
    # The signature keeps its hash (the pattern's identity); its content loses the refs.
    out["signature"], _ = _scrub(row.get("signature") or {}, keys)
    out["title"] = _scrub_text(row.get("title"), keys)
    out["summary"] = _scrub_text(row.get("summary"), keys)
    out["review_history"], _ = _scrub(row.get("review_history") or [], keys)
    promotion = row.get("promotion")
    if isinstance(promotion, dict):
        promotion = dict(promotion)
        promotion["risk_signals"] = [
            o for o in promotion.get("risk_signals") or [] if o.get("entity") not in keys
        ]
        out["promotion"] = promotion
    out["erasure_redactions"] = int(row.get("erasure_redactions") or 0) + 1
    out["evidence_fingerprint"] = evidence_fingerprint(out)
    return out


async def erase_pattern_discovery(tenant_id: str, refs: frozenset[str]) -> dict[str, Any]:
    """Returns ``{"status", "records_impacted", "detail", "hold"}``."""
    from shared.storage.lifecycle import StorageLifecycle

    from .registry import PatternDiscoveryRunRepository, PatternRegistryRepository

    keys = subject_keys(refs)
    lifecycle = StorageLifecycle()
    for ref in sorted(keys):
        hold = await lifecycle.active_hold(tenant_id, "discovered_patterns", ref)
        if hold is not None:
            return {"status": "skipped_legal_hold", "records_impacted": 0, "detail": {}, "hold": hold}

    registry = PatternRegistryRepository()
    runs = PatternDiscoveryRunRepository()
    redacted = deleted = 0
    touched: set[str] = set()
    for row in await registry.scan(tenant_id):
        if not names_subject(row, keys):
            continue
        pid = row["pattern_id"]
        touched.add(pid)
        updated = redact(row, keys)
        if updated["affected_entity_count"] < 2:
            deleted += await registry.delete_for_tenant_where(tenant_id, "pattern_id", [pid])
            continue

        def apply(current: dict[str, Any], _keys: set[str] = keys) -> dict[str, Any]:
            return redact(current, _keys)

        await registry.mutate(tenant_id, pid, apply)
        redacted += 1

    runs_deleted = 0
    if touched:
        offset = 0
        stale: list[str] = []
        while True:
            page = await runs.find_many(filters={"tenant_id": tenant_id}, limit=_PAGE, offset=offset)
            stale += [r["run_id"] for r in page
                      if r.get("tenant_id") == tenant_id and set(r.get("pattern_ids") or []) & touched]
            if len(page) < _PAGE:
                break
            offset += _PAGE
        if stale:
            runs_deleted = await runs.delete_for_tenant_where(tenant_id, "run_id", stale)
    logger.info("pattern_discovery.erasure", extra={"tenant_id": tenant_id, "redacted": redacted,
                                                     "deleted": deleted, "runs_deleted": runs_deleted})
    return {
        "status": "completed",
        "records_impacted": redacted + deleted + runs_deleted,
        "detail": {"patterns_redacted": redacted, "patterns_deleted": deleted, "runs_deleted": runs_deleted},
        "hold": None,
    }
