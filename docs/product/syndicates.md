---
title: Syndicates
slug: product-syndicates
section: concepts
visibility: P
audience: [buyer]
status: experimental
since_version: "0.1.0"
---

# Syndicates

Syndicates are entity groupings and segmentation views within the
intelligence graph, enabling cohort analysis and targeted
intelligence.

## Identity restatement contract

Syndicates groups use the governed Population 360 membership authority. A
population participates in Syndicates only when its metadata explicitly sets
`syndicates_group: true` and `syndicates_identity_merge_policy: union`. Untagged
populations and Cluster360 clusters are not treated as Syndicates groups.

After an identity merge, active membership rows for consumed entities are
joined to the selected survivor through `PopulationMembershipGovernor`, then
the consumed memberships are closed through the same governed writer. The
survivor join is consent checked before the old membership is left; provenance
retains the original evidence references and adds the identity decision ID.
Retries are idempotent, and the projection evidence reports how many groups and
memberships changed.

Split restatement uses the durable fragment split event. Membership evidence
references must use `syndicates:identity_alias:<alias-id>` or
`syndicates:identity_observation:<observation-id>`. Each reference is resolved
against the tenant-scoped identity repository and the event's actual moved
alias/observation IDs. A membership moves only when every reference resolves to
the same resulting fragment. Evidence that is missing, malformed, mixed across
fragments, or outside the split's tenant leaves that membership unchanged and
reports `syndicates_split_membership_evidence_incomplete` with per-membership
reason codes. Clear source-side memberships remain on the original entity.

## See Also

- `docs/product/lenses/syndicates.md` — Syndicates lens
