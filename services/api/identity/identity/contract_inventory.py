"""Read the installed identity contract inventory without substituting source assumptions."""
from __future__ import annotations

import json
import os
from pathlib import Path


REQUIRED_IDENTITY_CONTRACT_IDS = (
    "canonical-entity",
    "identity-claim",
    "identity-conflict",
    "identity-decision",
    "identity-edge",
    "identity-graph-version",
    "projection-restatement-job",
    "source-identity",
    "source-system",
)

REQUIRED_STAGING_IDENTITY_FLAGS = (
    "resolution_enabled",
    "auto_merge_enabled",
    "manual_review_enabled",
    "conflict_detection_enabled",
    "split_enabled",
    "manual_split_enabled",
    "auto_split_candidates_enabled",
    "sdk_late_binding_enabled",
    "anonymous_to_known_binding_enabled",
    "multi_sdk_stitching_enabled",
    "connector_backfill_enabled",
    "projection_restatement_enabled",
    "campaign_restatement_enabled",
    "value_restatement_enabled",
    "explainability_enabled",
    "activation_dashboard_enabled",
    "agent_resolution_enabled",
)


def observed_identity_contract_ids() -> list[str]:
    """Return contract names actually visible to this runtime.

    A deployed image may omit repository contract sources. That produces an
    empty list so proof validation fails closed instead of claiming the source
    tree's inventory is installed in the running service.
    """
    configured = os.getenv("AETHER_IDENTITY_CONTRACT_DIR")
    root = Path(configured) if configured else Path(__file__).resolve().parents[4] / "packages/shared/contracts/identity"
    index_path = root / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        entries = index.get("contracts")
        if not isinstance(entries, list) or not entries:
            return []
        observed: list[str] = []
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else None
            file_name = entry.get("file") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name or not isinstance(file_name, str):
                return []
            contract_path = root / file_name
            document = json.loads(contract_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or not document:
                return []
            observed.append(name)
        return sorted(set(observed)) if len(set(observed)) == len(observed) else []
    except (OSError, ValueError, TypeError):
        return []
