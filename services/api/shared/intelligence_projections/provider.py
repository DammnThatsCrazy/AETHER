"""Provider-neutral async contract for the intelligence projection plane (P0.5).

Every real 360 provider implements :class:`IntelligenceProjectionProvider`. The
runtime registry (``shared/intelligence_projections/registry.py``) depends ONLY
on this Protocol plus the plane contracts / errors — never on any provider
implementation.

This module is SDK-free: it imports no provider libraries and holds no
credentials or secrets. The projection plane is a fail-isolated runtime — one
broken projection must never take down the plane — so the Protocol deliberately
has no superclass and no write surface.
"""

from __future__ import annotations

import typing

from shared.intelligence_projections.contracts import (
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
)


class IntelligenceProjectionProvider(typing.Protocol):
    """Provider-neutral async contract every projection provider implements.

    A 360 is an intelligence projection over canonical Aether truth — never a
    competing system of record. Providers read canonical truth and project;
    they MUST NOT mutate canonical Aether state.
    """

    projection_id: str  # MUST be a registry id (INTELLIGENCE_PROJECTION_IDS)
    contract_version: str  # semver the provider was built against

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one projection over canonical Aether truth.

        Contract:

        * MUST NOT mutate canonical Aether state. Any graph write (when the
          projection's ``graphMutationPolicy == "canonical_gateway_only"``)
          goes through ``GraphMutationGateway.apply(MutationIntent)``.
        * MUST raise only :class:`ProjectionError
          <shared.intelligence_projections.errors.ProjectionError>` subclasses
          on failure (the registry fail-isolates these and any other exception).
        * MUST pass explicit ``[]`` for the required list fields — ``sections``,
          ``claims``, ``dependencyState``, ``degradedReasons`` — never omit them.
        """
        ...


__all__ = ["IntelligenceProjectionProvider"]
