"""Candidate lookup over unresolved CSV and lifecycle-committed provider claims.

This adapter exposes source evidence to the identify decision path without
turning claims into canonical aliases or selecting a canonical entity. All
candidate IDs and provenance remain server-side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.common.common import NotFoundError

from .claim_normalizer import normalize_email, normalize_phone
from .hashing import hash_value
from .repository import IdentityResolutionRepository

_MAX_CANDIDATE_MATCHES = 100
_PROVIDER_IDENTITY_SOURCES = frozenset({
    "amazon", "ebay", "etsy", "shopify", "tiktok", "walmart", "woocommerce",
})


@dataclass(frozen=True)
class ImportCandidateDecision:
    outcome: str
    reason_codes: list[str] = field(default_factory=list)
    candidate_source_identity_ids: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


class ImportIdentityCandidateAdapter:
    """Find matching unresolved CSV claims inside the caller's tenant."""

    def __init__(self, repo: IdentityResolutionRepository) -> None:
        self._repo = repo

    @staticmethod
    async def _is_committed_current_evidence(
        *, tenant_id: str, claim: dict, cache: dict[tuple[str, str], bool]
    ) -> bool:
        import_id = claim.get("import_id")
        commit_id = claim.get("import_commit_id")
        if not import_id or not commit_id:
            return False
        key = (str(import_id), str(commit_id))
        if key in cache:
            return cache[key]

        from repositories.imports_repo import get_imports_repository

        imports = get_imports_repository()
        try:
            session = await imports.get_session(tenant_id, key[0])
            commit = await imports.get_commit(tenant_id, key[1])
        except NotFoundError:
            # A missing durable commit/session makes the claim unusable.
            cache[key] = False
            return False

        valid = (
            session.get("tenant_id") == tenant_id
            and session.get("id") == key[0]
            and session.get("lifecycle_state") == "COMPLETED"
            and session.get("status") == "committed"
            and session.get("active_commit_id") == key[1]
            and not session.get("replay_in_progress")
            and commit.get("tenant_id") == tenant_id
            and commit.get("import_id") == key[0]
            and commit.get("commit_id") == key[1]
            and commit.get("status") == "committed"
            and not commit.get("rolled_back")
        )
        cache[key] = valid
        return valid

    async def evaluate(
        self,
        *,
        tenant_id: str,
        claims: dict[str, Any] | None,
        include_connectors: bool = True,
    ) -> ImportCandidateDecision:
        if not claims:
            return ImportCandidateDecision("no_match")

        matches_by_type: dict[str, dict[str, dict[str, Any]]] = {}
        connector_match_disabled = False
        durable_status_cache: dict[tuple[str, str], bool] = {}
        provider_anchor_cache: dict[str, dict[str, Any] | None] = {}
        for claim_type, normalizer in (
            ("email", normalize_email),
            ("phone", normalize_phone),
        ):
            raw_value = claims.get(claim_type)
            if not isinstance(raw_value, str) or not raw_value.strip():
                continue
            normalized = normalizer(raw_value)
            claim_digest = hash_value(normalized, scope=f"{claim_type}:{tenant_id}")
            if not normalized or not claim_digest:
                continue

            rows = await self._repo.find_claims_by_value(
                tenant_id,
                claim_type,
                claim_digest,
                limit=_MAX_CANDIDATE_MATCHES + 1,
            )
            # A capped lookup cannot establish that the candidate is unique.
            # Fail closed instead of treating the first page as the full result.
            if len(rows) > _MAX_CANDIDATE_MATCHES:
                return ImportCandidateDecision(
                    "blocked", ["import_identity_candidate_set_too_large"]
                )
            type_matches = matches_by_type.setdefault(claim_type, {})
            for claim in rows:
                if claim.get("tenant_id") != tenant_id:
                    continue
                source = await self._repo.get_source_identity(
                    str(claim.get("source_identity_id") or "")
                )
                if (
                    source is None
                    or source.get("tenant_id") != tenant_id
                    or source.get("status") != "unresolved"
                ):
                    continue

                source_system_id = str(source.get("source_system_id") or "")
                if source_system_id == "csv_import" and source.get("source_kind") == "csv":
                    if not await self._is_committed_current_evidence(
                        tenant_id=tenant_id,
                        claim=claim,
                        cache=durable_status_cache,
                    ):
                        continue
                elif (
                    source.get("source_kind") == "connector"
                    and source_system_id.split(".", 1)[0]
                    in _PROVIDER_IDENTITY_SOURCES
                ):
                    if not include_connectors:
                        connector_match_disabled = True
                        continue
                    claim_id = str(claim.get("id") or "")
                    if not claim_id:
                        continue
                    if claim_id not in provider_anchor_cache:
                        from services.identity.provider_evidence_anchors import (
                            ProviderIdentityEvidenceAnchorRepository,
                        )

                        # Provider account IDs may themselves contain colons
                        # (for example Shopify's ``shop:{domain}``). The
                        # connection ID is the final namespace component and
                        # is generated by this runtime, so split from the
                        # right while preserving the legacy namespace text.
                        namespace_prefix, separator, connection_id = str(
                            source.get("source_namespace") or ""
                        ).rpartition(":")
                        if not separator or not namespace_prefix or not connection_id:
                            provider_anchor_cache[claim_id] = None
                            continue
                        provider_anchor_cache[claim_id] = (
                            await ProviderIdentityEvidenceAnchorRepository().get_current_committed_anchor(
                                tenant_id=tenant_id,
                                claim_id=claim_id,
                                source_identity_id=str(source.get("id") or ""),
                                source_record_id=str(claim.get("source_record_id") or ""),
                                provider_identity=source_system_id,
                                connection_id=connection_id,
                                account_id=str(source.get("account_id") or ""),
                            )
                        )
                    if provider_anchor_cache[claim_id] is None:
                        continue
                    anchor = provider_anchor_cache[claim_id]
                    if (
                        claim.get("provider_raw_checksum") != anchor.get("raw_checksum")
                        or claim.get("provider_raw_schema_version")
                        != anchor.get("raw_schema_version")
                    ):
                        continue
                else:
                    continue

                source_id = str(source.get("id") or "")
                if not source_id:
                    continue
                type_matches[source_id] = {
                    "source_identity_id": source_id,
                    "provisional_canonical_entity_id": source.get("canonical_entity_id"),
                    "source_namespace": source.get("source_namespace"),
                    "source_record_id": claim.get("source_record_id"),
                    "import_id": claim.get("import_id"),
                    "import_commit_id": claim.get("import_commit_id"),
                    "claim_type": claim_type,
                    "claim_verification_status": claim.get("verification_status"),
                    "claim_id": claim.get("id"),
                    # Email/phone claim rows persist only tenant/type-scoped
                    # HMAC digests; never copy an incoming plaintext trait.
                    "claim_digest": claim.get("normalized_value"),
                }

        if connector_match_disabled:
            return ImportCandidateDecision(
                "blocked", ["connector_backfill_identity_resolution_disabled"]
            )

        per_type_candidates = [set(matches) for matches in matches_by_type.values() if matches]
        if not per_type_candidates:
            return ImportCandidateDecision("no_match")

        candidate_ids = sorted(set.union(*per_type_candidates))
        evidence = [
            item
            for matches in matches_by_type.values()
            for item in matches.values()
        ]

        if any(len(matches) > 1 for matches in matches_by_type.values()):
            return ImportCandidateDecision(
                "blocked",
                ["ambiguous_import_identity_claim"],
                candidate_ids,
                evidence,
            )

        if len(per_type_candidates) > 1:
            common = set.intersection(*per_type_candidates)
            if not common:
                return ImportCandidateDecision(
                    "blocked",
                    ["conflicting_import_identity_claims"],
                    candidate_ids,
                    evidence,
                )
            candidate_ids = sorted(common)

        return ImportCandidateDecision(
            "candidate",
            ["import_identity_candidate", "identity_match_requires_review"],
            candidate_ids,
            evidence,
        )
