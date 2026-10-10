"""Tenant-scoped Social360 projection over canonical Social Silver facts."""
from __future__ import annotations

from datetime import datetime, timezone

from shared.intelligence_projections.contracts import (
    ProjectionContext, ProjectionRequest, ProjectionResult, ProjectionSection,
)
from shared.intelligence_projections.generated_registry import INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from services.consent.authority import evaluate_consent
from services.silver.repositories.social_facts import (
    SocialCommunityFactsRepository, SocialConnectionFactsRepository,
    SocialContentFactsRepository, SocialIdentityFactsRepository,
    SocialInteractionFactsRepository, SocialMetricFactsRepository,
)


class Social360Provider(IntelligenceProjectionProvider):
    """Read existing authorized facts; never infer missing social metrics."""

    projection_id = "social360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    async def project(self, request: ProjectionRequest, context: ProjectionContext) -> ProjectionResult:
        if not request.tenantId or not request.subject.id:
            raise ValueError("tenant and subject are required")

        # Social360 is a historical relationship read. A fact's stored
        # consent_snapshot_id is provenance, not current authorization; consult
        # the server-owned receipt authority on every read and fail closed.
        consent_allowed, _ = await evaluate_consent(
            request.tenantId,
            request.subject.id,
            None,
            "analytics",
        )
        if not consent_allowed:
            sections = [
                ProjectionSection(
                    id=section_id,
                    state="suppressed",
                    title=title,
                )
                for section_id, title in (
                    ("evidence", "Evidence"),
                    ("findings", "Observed relationships"),
                    ("interactions", "Observed interactions"),
                    ("state", "Social identities"),
                    ("summary", "Social summary"),
                    ("timeline", "Interaction timeline"),
                )
            ]
            return ProjectionResult(
                projectionId=self.projection_id,
                tenantId=request.tenantId,
                contractVersion=self.contract_version,
                sections=sections,
                claims=[],
                dependencyState=context.dependencyState,
                generatedAt=datetime.now(timezone.utc).isoformat(),
                degradedReasons=["consent_required"],
            )

        identity_rows = await SocialIdentityFactsRepository().list_for_tenant(
            request.tenantId, limit=500
        )
        identities = [
            row for row in identity_rows
            if row.get("canonical_entity_ref") == request.subject.id
        ]
        identity_ids = {
            str(row.get("social_identity_id")) for row in identities
            if row.get("social_identity_id")
        }
        connection_rows = await SocialConnectionFactsRepository().list_for_tenant(
            request.tenantId, limit=500
        ) if identity_ids else []
        connections = [
            row for row in connection_rows
            if row.get("source_social_identity_ref") in identity_ids
            or row.get("target_social_identity_ref") in identity_ids
        ]
        interaction_rows = await SocialInteractionFactsRepository().list_for_tenant(
            request.tenantId, limit=500
        ) if identity_ids else []
        interactions = [
            row for row in interaction_rows
            if row.get("actor_social_identity_ref") in identity_ids
            or row.get("target_social_identity_ref") in identity_ids
        ]
        content_rows = await SocialContentFactsRepository().list_for_tenant(
            request.tenantId, limit=500
        ) if identity_ids else []
        content = [row for row in content_rows
                   if row.get("author_social_identity_ref") in identity_ids]
        community_rows = await SocialCommunityFactsRepository().list_for_tenant(
            request.tenantId, limit=500
        ) if identity_ids else []
        communities = [row for row in community_rows
                       if row.get("social_identity_ref") in identity_ids]
        metric_rows = await SocialMetricFactsRepository().list_for_tenant(
            request.tenantId, limit=500
        ) if identity_ids else []
        metrics = [row for row in metric_rows
                   if row.get("social_identity_ref") in identity_ids]

        include = set(request.includeSections or (
            "evidence", "findings", "interactions", "state", "summary", "timeline"
        ))
        sections = []
        def visible(row: dict, fields: tuple[str, ...]) -> dict:
            # Raw payload and content fields never leave Social Silver through
            # this projection; only typed facts and evidence references do.
            return {key: row.get(key) for key in fields if row.get(key) is not None}

        identity_items = [visible(row, (
            "social_identity_id", "provider_identity", "account_type",
            "verification_state", "resolution_state", "resolution_confidence",
            "identity_evidence_refs",
        )) for row in identities]
        connection_items = [visible(row, (
            "source_social_identity_ref", "target_social_identity_ref",
            "connection_type", "directionality", "proof_level", "claim_type",
            "evidence_refs", "contradictory_evidence_refs",
        )) for row in connections]
        interaction_items = [visible(row, (
            "interaction_id", "actor_social_identity_ref",
            "target_social_identity_ref", "interaction_type", "observed_at",
            "machine_classification", "human_qualification", "evidence_refs",
        )) for row in interactions]
        content_items = [visible(row, (
            "content_id", "author_social_identity_ref", "content_type",
            "provider_content_subtype", "parent_content_ref", "root_content_ref",
            "published_at", "edited_at", "deleted_at", "content_hash",
            "semantic_ref", "narrative_refs", "campaign_ref",
            "incentive_context_ref", "evidence_refs",
        )) for row in content]
        community_items = [visible(row, (
            "membership_id", "social_identity_ref", "community_ref",
            "membership_role", "provider_membership_role", "valid_from",
            "valid_to", "observed_at", "evidence_refs",
        )) for row in communities]
        metric_items = [visible(row, (
            "metric_observation_id", "social_identity_ref", "metric_name",
            "value", "unit", "status", "metric_window", "population",
            "observed_at", "computation_ref", "quality", "evidence_refs",
        )) for row in metrics]
        evidence_refs = sorted({
            str(ref)
            for row in identities + connections + interactions + content + communities + metrics
            for field in ("identity_evidence_refs", "evidence_refs", "contradictory_evidence_refs")
            for ref in (row.get(field) or [])
            if ref
        })
        section_data = {
            "evidence": ("Evidence", bool(evidence_refs), {"items": evidence_refs}),
            "findings": ("Observed relationships and communities", bool(connection_items or community_items), {
                "relationships": connection_items, "communityMemberships": community_items,
            }),
            "interactions": ("Observed interactions and content", bool(interaction_items or content_items), {
                "interactions": interaction_items, "content": content_items,
            }),
            "state": ("Social identities and measured metrics", bool(identity_items or metric_items), {
                "identities": identity_items, "metrics": metric_items,
            }),
            "summary": ("Social summary", bool(identity_items or connection_items or interaction_items or content_items or community_items or metric_items), {
                "identityCount": len(identity_items),
                "relationshipCount": len(connection_items),
                "communityMembershipCount": len(community_items),
                "interactionCount": len(interaction_items),
                "contentObservationCount": len(content_items),
                "metricObservationCount": len(metric_items),
            }),
            "timeline": ("Interaction timeline", bool(interaction_items), {
                "items": sorted(
                    interaction_items + [
                        {**item, "observed_at": item.get("published_at")}
                        for item in content_items if item.get("published_at")
                    ], key=lambda item: str(item.get("observed_at") or ""),
                ),
            }),
        }
        for section_id in ("evidence", "findings", "interactions", "state", "summary", "timeline"):
            if section_id in include:
                title, has_data, content = section_data[section_id]
                sections.append(ProjectionSection(
                    id=section_id,
                    state="available" if has_data else "unknown",
                    title=title,
                    content=content,
                ))

        # A capped source read is explicit; counts never imply absence or zero.
        capped = any(len(rows) >= 500 for rows in (
            identity_rows, connection_rows, interaction_rows, content_rows,
            community_rows, metric_rows,
        ))
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=context.dependencyState,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            degradedReasons=["source_read_capped"] if capped else [],
        )


def register_provider(registry) -> str:
    return registry.register(Social360Provider(), source="social_silver")
