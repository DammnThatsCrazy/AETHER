"""Instrumentation-as-code manifest — parse, validate, dry-run diff. Pure, no I/O.

A tenant manifest is a plain dict (already loaded from YAML/JSON) declaring
the product tree:

    product:  {stable_id, display_name, ...}          (required, exactly one)
    areas:    [{stable_id, display_name, ...}]         parent = product
    features: [{stable_id, display_name, area_id?}]    parent = area or product
    surfaces: [{stable_id, display_name, feature_id?}] parent = feature or product
    controls: [{stable_id, display_name, surface_id?}] parent = surface or product
    outcomes: [{stable_id, display_name, feature_id?}] folded into node metadata
    version:  int >= 1                                 stamped on every node

Outcomes are not catalog nodes (kind vocabulary is closed); each outcome is
attached to its referenced feature's ``metadata["outcomes"]``, or to the
product's when it names no feature.
"""

from __future__ import annotations

from typing import Any, Optional, get_args

from services.product_catalog.models import CatalogNode, CatalogNodeStatus

_ALLOWED_TOP_LEVEL = {"product", "areas", "features", "surfaces", "controls", "outcomes", "version"}
_ALLOWED_STATUS = set(get_args(CatalogNodeStatus))
# Optional per-entry fields copied through to the node verbatim.
_OPTIONAL_ENTRY_FIELDS = ("description", "owner", "status", "tags", "metadata", "valid_from", "valid_to")
_ALLOWED_ENTRY_FIELDS = {"stable_id", "display_name", *_OPTIONAL_ENTRY_FIELDS}


def _check_entry(section: str, index: int, entry: Any, parent_ref: Optional[str], errors: list[str]) -> None:
    where = f"{section}[{index}]"
    if not isinstance(entry, dict):
        errors.append(f"{where}: must be a mapping")
        return
    for key in ("stable_id", "display_name"):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{where}: '{key}' is required and must be a non-empty string")
    status = entry.get("status")
    if status is not None and status not in _ALLOWED_STATUS:
        errors.append(f"{where}: status {status!r} not in {sorted(_ALLOWED_STATUS)}")
    tags = entry.get("tags")
    if tags is not None and (not isinstance(tags, list) or any(not isinstance(t, str) for t in tags)):
        errors.append(f"{where}: tags must be a list of strings")
    metadata = entry.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append(f"{where}: metadata must be a mapping")
    allowed = _ALLOWED_ENTRY_FIELDS | ({parent_ref} if parent_ref else set())
    unknown = sorted(set(entry) - allowed)
    if unknown:
        errors.append(f"{where}: unknown field(s) {unknown}")


def validate_manifest(doc: Any) -> list[str]:
    """Validate a manifest document. Returns a list of errors ([] = valid)."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["manifest must be a mapping"]

    unknown = sorted(set(doc) - _ALLOWED_TOP_LEVEL)
    if unknown:
        errors.append(f"unknown top-level key(s) {unknown}")

    version = doc.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errors.append("version must be an integer >= 1")

    product = doc.get("product")
    if not isinstance(product, dict):
        errors.append("product: required and must be a mapping")
    else:
        _check_entry("product", 0, product, parent_ref=None, errors=errors)

    sections: dict[str, Optional[str]] = {
        "areas": None,
        "features": "area_id",
        "surfaces": "feature_id",
        "controls": "surface_id",
        "outcomes": "feature_id",
    }
    ids_by_section: dict[str, set[str]] = {}
    seen_ids: dict[str, str] = {}
    if isinstance(product, dict) and isinstance(product.get("stable_id"), str):
        seen_ids[product["stable_id"]] = "product"

    for section, parent_ref in sections.items():
        entries = doc.get(section, [])
        if not isinstance(entries, list):
            errors.append(f"{section}: must be a list")
            continue
        ids: set[str] = set()
        for i, entry in enumerate(entries):
            _check_entry(section, i, entry, parent_ref, errors)
            if isinstance(entry, dict):
                sid = entry.get("stable_id")
                if isinstance(sid, str) and sid.strip():
                    if sid in seen_ids:
                        errors.append(
                            f"{section}[{i}]: duplicate stable_id {sid!r} (already used in {seen_ids[sid]})"
                        )
                    else:
                        seen_ids[sid] = section
                        ids.add(sid)
        ids_by_section[section] = ids

    # Parent references must resolve within the manifest.
    ref_targets = {"area_id": "areas", "feature_id": "features", "surface_id": "surfaces"}
    for section, parent_ref in sections.items():
        if parent_ref is None:
            continue
        entries = doc.get(section, [])
        if not isinstance(entries, list):
            continue
        target_ids = ids_by_section.get(ref_targets[parent_ref], set())
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            ref = entry.get(parent_ref)
            if ref is None:
                continue
            if not isinstance(ref, str) or ref not in target_ids:
                errors.append(
                    f"{section}[{i}]: {parent_ref} {ref!r} does not reference a declared "
                    f"{ref_targets[parent_ref]} entry"
                )
    return errors


def _node(
    kind: str,
    entry: dict[str, Any],
    tenant_id: str,
    version: int,
    parent_id: Optional[str],
    path_prefix: str,
) -> CatalogNode:
    fields: dict[str, Any] = {k: entry[k] for k in _OPTIONAL_ENTRY_FIELDS if entry.get(k) is not None}
    return CatalogNode(
        kind=kind,  # type: ignore[arg-type]
        stable_id=entry["stable_id"],
        tenant_id=tenant_id,
        display_name=entry["display_name"],
        parent_id=parent_id,
        path=f"{path_prefix}/{entry['stable_id']}" if path_prefix else entry["stable_id"],
        version=version,
        **fields,
    )


def manifest_to_nodes(doc: dict[str, Any], tenant_id: str) -> list[CatalogNode]:
    """Convert a VALID manifest into CatalogNodes. Raises ValueError if invalid."""
    errors = validate_manifest(doc)
    if errors:
        raise ValueError(f"invalid manifest: {errors}")

    version = doc.get("version", 1)
    product_entry = dict(doc["product"])
    product_id = product_entry["stable_id"]

    # Fold outcomes into their owning feature's metadata (or the product's).
    outcomes_by_owner: dict[Optional[str], list[dict[str, Any]]] = {}
    for outcome in doc.get("outcomes", []):
        owner = outcome.get("feature_id")
        record = {k: v for k, v in outcome.items() if k != "feature_id"}
        outcomes_by_owner.setdefault(owner, []).append(record)

    def _with_outcomes(entry: dict[str, Any], owner_key: Optional[str]) -> dict[str, Any]:
        owned = outcomes_by_owner.get(owner_key)
        if not owned:
            return entry
        entry = dict(entry)
        metadata = dict(entry.get("metadata") or {})
        metadata["outcomes"] = owned
        entry["metadata"] = metadata
        return entry

    nodes: list[CatalogNode] = [
        _node("product", _with_outcomes(product_entry, None), tenant_id, version, None, "")
    ]

    paths: dict[str, str] = {product_id: product_id}
    for section, kind, parent_ref in (
        ("areas", "product_area", None),
        ("features", "feature", "area_id"),
        ("surfaces", "surface", "feature_id"),
        ("controls", "control", "surface_id"),
    ):
        for entry in doc.get(section, []):
            parent = entry.get(parent_ref) if parent_ref else None
            parent_id = parent or product_id
            entry_fields = {k: v for k, v in entry.items() if k != parent_ref}
            if section == "features":
                entry_fields = _with_outcomes(entry_fields, entry["stable_id"])
            node = _node(kind, entry_fields, tenant_id, version, parent_id, paths[parent_id])
            paths[node.stable_id] = node.path or node.stable_id
            nodes.append(node)
    return nodes


def dry_run_diff(desired: list[CatalogNode], existing: list[CatalogNode]) -> dict[str, list[str]]:
    """Diff a desired node set against an existing one, keyed by stable_id.

    Returns sorted stable_id lists: added / changed / removed / unchanged.
    Pure comparison of the full node contract — no persistence.
    """
    desired_by_id = {n.stable_id: n for n in desired}
    existing_by_id = {n.stable_id: n for n in existing}
    added = sorted(set(desired_by_id) - set(existing_by_id))
    removed = sorted(set(existing_by_id) - set(desired_by_id))
    changed: list[str] = []
    unchanged: list[str] = []
    for sid in sorted(set(desired_by_id) & set(existing_by_id)):
        if desired_by_id[sid].model_dump() == existing_by_id[sid].model_dump():
            unchanged.append(sid)
        else:
            changed.append(sid)
    return {"added": added, "changed": changed, "removed": removed, "unchanged": unchanged}
