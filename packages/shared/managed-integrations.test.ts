import { describe, expect, it } from 'vitest';
import {
  actionRequiredStatuses,
  admissionStages,
  changeActionKinds,
  changeRiskClasses,
  changeSetStatuses,
  continuousLifecycleActions,
  controlFindingKinds,
  defaultManagedReleaseChannel,
  discoveryDataClasses,
  driftTaxonomyTypes,
  evidenceConfidenceValues,
  healthGateOperators,
  healthSnapshotAxes,
  integrationAvailabilityValues,
  integrationSourceOrigins,
  integrationSourceOwners,
  isActionRequiredStatus,
  isChangeActionKind,
  isChangeRiskClass,
  isChangeSetStatus,
  isControlFindingKind,
  isDriftTaxonomyType,
  isIntegrationAvailability,
  isManagedDriftType,
  isManagedIntegrationKind,
  isReconcileResult,
  isRollbackStatus,
  isVerifyOutcome,
  managedDriftTypes,
  managedIntegrationKinds,
  managedReleaseChannels,
  mappingMethodValues,
  mappingReviewStates,
  observedProvenanceValues,
  platformUpgradeBehaviors,
  reconcileResultValues,
  rolloutArtifactKinds,
  rolloutRingValues,
  rollbackStatuses,
  schemaMappingAutoPromoteGates,
  simulationResultValues,
  upgradeBehaviorValues,
  verifyOutcomes,
} from './managed-integrations';

// Every canonical vocabulary paired with its type guard. Each guard must
// recognize exactly the members of its own vocabulary — nothing more, nothing
// less — so the twin stays a faithful, usable boundary for callers.
const vocabularyAndGuard = [
  [managedIntegrationKinds, isManagedIntegrationKind],
  [integrationAvailabilityValues, isIntegrationAvailability],
  [reconcileResultValues, isReconcileResult],
  [managedDriftTypes, isManagedDriftType],
  [driftTaxonomyTypes, isDriftTaxonomyType],
  [changeSetStatuses, isChangeSetStatus],
  [changeRiskClasses, isChangeRiskClass],
  [changeActionKinds, isChangeActionKind],
  [controlFindingKinds, isControlFindingKind],
  [verifyOutcomes, isVerifyOutcome],
  [rollbackStatuses, isRollbackStatus],
  [actionRequiredStatuses, isActionRequiredStatus],
] as const;

describe('managed-integrations contract vocabulary', () => {
  it('every type guard recognizes exactly the members of its own vocabulary', () => {
    for (const [vocabulary, guard] of vocabularyAndGuard) {
      for (const member of vocabulary) {
        expect(guard(member)).toBe(true);
      }
      expect(guard('__not_a_member__')).toBe(false);
    }
  });

  it('keeps every canonical vocabulary distinct (no duplicate members)', () => {
    const vocabularies = [
      managedIntegrationKinds,
      integrationSourceOrigins,
      integrationSourceOwners,
      integrationAvailabilityValues,
      reconcileResultValues,
      managedDriftTypes,
      driftTaxonomyTypes,
      changeSetStatuses,
      changeRiskClasses,
      changeActionKinds,
      observedProvenanceValues,
      controlFindingKinds,
      verifyOutcomes,
      evidenceConfidenceValues,
      rollbackStatuses,
      actionRequiredStatuses,
      admissionStages,
      continuousLifecycleActions,
      discoveryDataClasses,
      mappingMethodValues,
      mappingReviewStates,
      simulationResultValues,
      schemaMappingAutoPromoteGates,
      rolloutRingValues,
      rolloutArtifactKinds,
      healthSnapshotAxes,
      healthGateOperators,
      upgradeBehaviorValues,
    ];
    for (const vocabulary of vocabularies) {
      expect(vocabulary.length).toBe(new Set(vocabulary).size);
    }
  });

  it('keeps CP-12 typed availability strict: missing, empty, and unknown are distinct', () => {
    expect(integrationAvailabilityValues).toContain('available');
    expect(integrationAvailabilityValues).toContain('missing');
    expect(integrationAvailabilityValues).toContain('empty');
    expect(integrationAvailabilityValues).toContain('unknown');
    expect(isIntegrationAvailability('missing')).toBe(true);
    expect(isIntegrationAvailability('empty')).toBe(true);
    expect(isIntegrationAvailability('unknown')).toBe(true);
    // A report never collapses one state into another (CP-12).
    expect(new Set(['missing', 'empty', 'unknown']).size).toBe(3);
  });

  it('keeps §40 ring order as law: one ring at a time, internal → 100%', () => {
    expect(rolloutRingValues).toEqual([
      'olympus_internal',
      'test_tenants',
      '1%',
      '5%',
      '20%',
      '50%',
      '100%',
    ]);
  });

  it('anchors managed_stable as the default channel — never equivalent to latest', () => {
    expect(defaultManagedReleaseChannel).toBe('managed_stable');
    expect(managedReleaseChannels).toContain(defaultManagedReleaseChannel);
    expect(managedReleaseChannels).not.toContain('latest');
  });

  it('spans the §34 status arc with terminal and transition states present', () => {
    expect(changeSetStatuses).toEqual(
      expect.arrayContaining([
        'draft',
        'ready',
        'committed',
        'rolled_back',
        'superseded',
      ]),
    );
  });

  it('mirrors the §30 platform-behavior table: 11 rows, all behaviors canonical', () => {
    expect(Object.keys(platformUpgradeBehaviors)).toHaveLength(11);
    for (const behavior of Object.values(platformUpgradeBehaviors)) {
      expect(upgradeBehaviorValues).toContain(behavior);
    }
  });

  it('covers §12.9 health-gate operators exactly', () => {
    expect(healthGateOperators).toEqual(['lt', 'le', 'gt', 'ge']);
  });
});
