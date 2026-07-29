# Frontend Intelligence Five-Phase Readiness

**Branch:** `codex/set-up-aether-production-engineering-plan`

**Assessment date:** 2026-07-29

**Verdict:** **NO-GO**

The branch implements the first four product slices as reviewable commits. This
report is the Phase 5 documentation and evidence checkpoint; it does not convert
local implementation evidence into a production-readiness claim.

## Delivered branch slices

| Phase | Commit | Delivered contract |
| --- | --- | --- |
| 1 | `68096029` | Typed canonical exploration client/provider, cancellation and stale-response protection, server-driven table behaviors, and canonical truth/capability presentation |
| 2 | `8ef0b320` | Canonical exploration context across profile, graph, cluster, campaign, journey, and geo workflows |
| 3 | `d32a9371` | Mounted comparison workbench for entity and history modes, fail-closed preflight/finding truth, exact Noesis context transport, and durable saved views |
| 4 | `8a13b580` | Canonical domain truth/readiness/units and response-postcondition checks on selected connector, reward, delivery, stablecoin, derivatives, interop, and payment-rail paths |

The comparison surface intentionally does not advertise unsupported modes.
Investigation and export actions remain unavailable where the mounted APIs
cannot preserve the exact canonical context. Phase 4 likewise does not infer a
provider is live from configuration, render missing measurements as zero, or
claim that a mutation succeeded before its response supplies the required
postcondition.

PR #494, already merged into the branch baseline, separately supplies the
versioned backend demo seed/status/verify/reset pipeline. Its reset is
provenance-scoped and tenant-isolated, production refuses seed/reset, and
staging requires explicit policy and an allowlisted tenant. It is not new work
in these four commits.

## Evidence present

- Focused unit and component tests exercise exploration validation,
  cancellation, stale-response handling, table semantics, truth states,
  entity-context transport, comparison policy/finding truth, Noesis context
  round trips, domain truth, and operational postconditions.
- After Phase 4, the complete Aether suite passed with 53 files and 287 tests;
  the complete Kyber suite passed with 55 files and 482 tests. Both application
  typechecks passed.
- All 33 repository documentation/consistency gates, frontend data-truth
  validation, and enforced route-state coverage passed locally after Phase 4.
- Hosted execution is available. The Aether unit-test workflow, SDK JavaScript
  validation, TypeScript, Android, iOS, staging preflight dry run, change
  detection, and PR-size checks passed on the Phase 4 head; other backend and
  consistency jobs exposed the concrete blockers listed below.
- The hosted Noesis test selection passes locally after correcting its legacy
  operator fixtures: 181 tests passed. The derivatives release selection also
  passes 5 tests after replacing removed fixture helpers with caller-supplied
  test observations and explicit release-gate evidence.
- The local canonical gate passed its first 38 repository checks, including
  strict documentation drift, generated-artifact cleanliness, contracts,
  ownership, data truth, and route state. Its next clean-install step was
  blocked by permissions on the workstation npm cache, which is an environment
  failure and not passing evidence for the remaining checks.
- The route-state matrix classifies `/compare` honestly: it is a mounted Aether
  surface and is parity-exempt in Kyber rather than being marked as a feature
  that Kyber does not implement.

These results support branch review. They are not substitutes for the release
evidence below.

## Release blockers

1. The complete core Python suite must collect and execute successfully. The
   final-head hosted run passed 4,718 tests and reported 38 failures across commerce,
   auth/API-key local profiles, graph/data-quality async compatibility,
   connectors, demo-profile validation, route inventory/matrix, Stripe billing,
   value semantics/price sources, and Terraform profile compatibility. Its one
   earlier derivatives collection error was a stale test import and is fixed in
   the Phase 5 commit; the final-head suite now collects cleanly, but the
   remaining failures cannot be waived by frontend results.
2. The hosted Noesis suite exposed legacy operator fixtures that did not carry
   the explicit `kyber:operator` capability required by the current
   authorization contract. The Phase 5 gate work updates those fixtures without
   weakening the service gate; the hosted workflow must pass after the final
   commit is pushed.
3. The Phase 4 hosted Kyber browser smoke run reached Playwright but all 10
   unauthenticated-boundary checks failed to find the expected sign-in surface.
   The first Phase 5 run stopped earlier on a component-test race; the follow-up
   waits for the settled UI and passes the full component selection, but the
   hosted job must rerun through Playwright. A component-test pass does not
   substitute for the missing browser contract.
4. Credentialed staging must record live `/v1/explore` query IDs and filter
   dispositions; empty, partial, unavailable, suppressed, credential-waiting
   and failed states; and provider/readiness transitions without synthetic
   population.
5. Empty, seeded, reset, and cross-tenant-isolation browser journeys must be
   captured against the real backend. Comparison history and exact-context
   saved-view reproduction must be included.
6. Connector activation, reward delivery, and Kyber delivery replay require
   governed safe-rail rehearsals with durable server-side outcome evidence.
   Broader agent, import, and consent route families still need
   contract-by-contract productization review.
7. The release bundle still needs the required accessibility,
   performance/load, migration-head, worker-readiness, rollback, artifact
   checksum, and staging wake/sleep evidence.

## Promotion rule

Keep the verdict **NO-GO** until all required hosted suites have executed and
passed, the credentialed staging artifacts are attached and checksummed, and
every remaining route family either has a verified canonical contract or is
explicitly unavailable. External runner or credential blockers explain missing
evidence; they do not satisfy the gate.

## Follow-up notes

- Rerun the existing workflows on the final Phase 5 commit; do not create a
  parallel readiness vocabulary or a second release gate.
- Capture exact backend request IDs, dispositions, readiness states and durable
  outcome identifiers in staging evidence. Screenshots without those facts are
  supporting material only.
- Preserve the current fail-closed UI behavior when expanding agent, import,
  consent, investigation, export, or additional domain routes.
- Update this report only from attached artifacts and completed hosted jobs.
  Change the verdict to GO only in the same commit that records those results.
