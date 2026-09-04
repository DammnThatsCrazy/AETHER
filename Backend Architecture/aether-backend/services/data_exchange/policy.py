"""Data Exchange Plane policy layer (M0: declarative intent, nothing wired).

This module records *intended* governance and authorization decisions for the
Data Exchange Plane so M3/M4 land them on the repository's canonical seams
instead of inventing parallel ones:

- Classification policy drives commit gating.  ``secret`` / ``credential``
  content is blocked from graph commit by default (see
  ``DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS`` in ``contracts.py``) unless an
  elevated tenant policy explicitly permits it.  When the analyzer (M3) feeds
  these labels, they map onto the import engine's existing column-level
  sensitivity vocabulary (``services/imports/contracts.py``) and the shared
  privacy classification (``shared/privacy/classification.py``).
- Authorization is enforced at request time on the canonical RBAC registry
  (``services/security/contracts.py`` ``GovernanceDomain`` + ``ROLE_SPECS``
  in ``services/security/access_control.py``).  The permission ids below are
  the intended Data Exchange domain grants; they are **not registered** until
  M3 adds the domain to that registry and its TS mirror
  (``packages/shared/security-governance.ts``).
- Every artifact download is re-authorized at download time, never only at
  generation time; upload tokens are tenant + object-key scoped (M2 signed
  transfers).
"""

from __future__ import annotations

from typing import Final

# Intended data-exchange permission ids (GovernanceDomain grants).  Registered
# in services/security/contracts.py + packages/shared/security-governance.ts +
# ROLE_SPECS when the first data-exchange routes mount (M3).
DATA_EXCHANGE_PERMISSIONS: Final[tuple[str, ...]] = (
    "data_exchange.read",
    "data_exchange.import.create",
    "data_exchange.import.map",
    "data_exchange.import.approve",
    "data_exchange.import.commit",
    "data_exchange.import.rollback",
    "data_exchange.export.create",
    "data_exchange.export.download",
    "data_exchange.report.create",
    "data_exchange.settings.manage",
)

# Classifications that are always safe to surface in tenant UI without
# redaction (everything else is gated by governance field policy on export).
DATA_EXCHANGE_UI_SAFE_CLASSIFICATIONS: Final[tuple[str, ...]] = (
    "none",
    "location",
    "temporal",
)


def classification_blocked_by_default(classification: str) -> bool:
    """Return True when content of ``classification`` must not reach the graph
    without an elevated tenant policy.

    Day-one defaults: secrets and credentials are blocked; everything else
    proceeds subject to tenant/legal governance policy.
    """
    return classification in {"secret", "credential"}
