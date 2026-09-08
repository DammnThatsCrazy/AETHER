import { describe, expect, it } from 'vitest';
import {
  collaborativeRightsProfileDefaults,
  disclosureBoundaries,
  intelligenceRightsProfiles,
  learningClasses,
  lifecycleActions,
  modelRevocationStates,
  olympusPurposes,
  ownershipClasses,
  rightsDecisionDispositions,
  rightsDerivationClasses,
  sovereignRightsProfileDefaults,
  standardDisclosureAuthority,
  standardGeneratedOutputRights,
  standardRightsProfileDefaults,
  type DisclosureBoundary,
  type IntelligenceRightsProfile,
  type LearningClass,
  type LifecycleAction,
  type ModelRevocationState,
  type OlympusPurpose,
  type OwnershipClass,
  type RightsDecisionDisposition,
  type RightsDerivationClass,
} from './data-rights';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** True when s is a non-empty lowercase snake_case string (a..z0..9, `_` separators). */
function isLowerSnake(s: string): boolean {
  return /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(s);
}

const SNAKE_ARRAYS: Record<string, readonly string[]> = {
  rightsDerivationClasses,
  learningClasses,
  ownershipClasses,
  intelligenceRightsProfiles,
  disclosureBoundaries,
  olympusPurposes,
  lifecycleActions,
  modelRevocationStates,
  rightsDecisionDispositions,
};

describe('data-rights structured authority vocabularies', () => {
  it('every vocabulary array is non-empty and every member is a non-empty lowercase snake string', () => {
    for (const [arrayName, members] of Object.entries(SNAKE_ARRAYS)) {
      expect(members.length, `${arrayName} must not be empty`).toBeGreaterThan(0);
      for (const member of members) {
        expect(member.length, `${arrayName} member must be non-empty`).toBeGreaterThan(0);
        expect(
          isLowerSnake(member),
          `${arrayName} member ${JSON.stringify(member)} must be a lowercase snake_case string`,
        ).toBe(true);
      }
    }
  });

  it('each vocabulary array has unique members', () => {
    for (const [arrayName, members] of Object.entries(SNAKE_ARRAYS)) {
      expect(new Set(members).size, `${arrayName} must contain unique members`).toBe(members.length);
    }
  });

  it('rightsDerivationClasses is the frozen blueprint §5 set of 8', () => {
    const expected: RightsDerivationClass[] = [
      'source_representation',
      'normalized',
      'tenant_identifiable_derivative',
      'aether_generated_intelligence',
      'aggregated',
      'generalized',
      'model_derived',
      'platform_knowledge',
    ];
    expect(rightsDerivationClasses).toHaveLength(8);
    expect([...rightsDerivationClasses]).toEqual(expected);
  });

  it('learningClasses is the frozen blueprint §3.3 set of 9', () => {
    const expected: LearningClass[] = [
      'inference',
      'tenant_adaptation',
      'generalized_learning',
      'resolver_calibration',
      'ontology_learning',
      'schema_mapping_learning',
      'benchmarking',
      'contributed_model_training',
      'olympus_internal_intelligence',
    ];
    expect(learningClasses).toHaveLength(9);
    expect([...learningClasses]).toEqual(expected);
  });

  it('ownershipClasses is the frozen blueprint §2 set of 4', () => {
    const expected: OwnershipClass[] = [
      'contributed_source',
      'canonicalized',
      'aether_generated_intelligence',
      'generalized_knowledge',
    ];
    expect(ownershipClasses).toHaveLength(4);
    expect([...ownershipClasses]).toEqual(expected);
  });

  it('intelligenceRightsProfiles is the frozen blueprint §3.6 set of 4', () => {
    const expected: IntelligenceRightsProfile[] = ['sovereign', 'private', 'standard', 'collaborative'];
    expect(intelligenceRightsProfiles).toHaveLength(4);
    expect([...intelligenceRightsProfiles]).toEqual(expected);
  });

  it('disclosureBoundaries is the frozen blueprint §3.4 set of 6 (governed is NOT a boundary member)', () => {
    const expected: DisclosureBoundary[] = [
      'tenant_internal',
      'olympus_internal',
      'cross_tenant_identifiable',
      'external_identifiable',
      'generalized_cross_tenant',
      'generalized_external',
    ];
    expect(disclosureBoundaries).toHaveLength(6);
    expect([...disclosureBoundaries]).toEqual(expected);
    expect(disclosureBoundaries).not.toContain('governed' as DisclosureBoundary);
  });

  it('olympusPurposes is the frozen blueprint §7 set of 10', () => {
    const expected: OlympusPurpose[] = [
      'platform_research',
      'model_improvement',
      'security_research',
      'fraud_research',
      'resolver_calibration',
      'ontology_research',
      'product_analytics',
      'benchmark_analysis',
      'support_investigation',
      'incident_response',
    ];
    expect(olympusPurposes).toHaveLength(10);
    expect([...olympusPurposes]).toEqual(expected);
  });

  it('lifecycleActions is the frozen blueprint §9 set of 12', () => {
    const expected: LifecycleAction[] = [
      'preserve',
      'delete',
      'hard_delete',
      'tombstone',
      'quarantine',
      'suppress',
      'invalidate',
      'recompute',
      'retrain',
      'anonymize',
      'generalize',
      'legal_hold',
    ];
    expect(lifecycleActions).toHaveLength(12);
    expect([...lifecycleActions]).toEqual(expected);
  });

  it('modelRevocationStates is the frozen blueprint §8 set of 6', () => {
    const expected: ModelRevocationState[] = [
      'no_action_required',
      'retrain_required',
      'model_quarantine_required',
      'evaluation_required',
      'legal_review_required',
      'blocked',
    ];
    expect(modelRevocationStates).toHaveLength(6);
    expect([...modelRevocationStates]).toEqual(expected);
  });

  it('rightsDecisionDispositions is the frozen blueprint §4 set of 4', () => {
    const expected: RightsDecisionDisposition[] = ['allowed', 'denied', 'redacted', 'suppressed'];
    expect(rightsDecisionDispositions).toHaveLength(4);
    expect([...rightsDecisionDispositions]).toEqual(expected);
  });
});

describe('data-rights preset factories', () => {
  it('standardRightsProfileDefaults: yes retention, bounded Olympus internal intelligence, NO contributed model training', () => {
    expect(standardRightsProfileDefaults.generated_output_retention).toBe('yes');
    expect(standardRightsProfileDefaults.generalized_learning).toBe(true);
    expect(standardRightsProfileDefaults.olympus_internal_intelligence).toBe(true);
    expect(standardRightsProfileDefaults.contributed_model_training).toBe(false);
  });

  it('collaborativeRightsProfileDefaults: yes retention, contributed model training explicitly governed ON', () => {
    expect(collaborativeRightsProfileDefaults.generated_output_retention).toBe('yes');
    expect(collaborativeRightsProfileDefaults.generalized_learning).toBe(true);
    expect(collaborativeRightsProfileDefaults.olympus_internal_intelligence).toBe(true);
    expect(collaborativeRightsProfileDefaults.contributed_model_training).toBe(true);
  });

  it('sovereignRightsProfileDefaults: minimal retention and every learning/training flag false', () => {
    expect(sovereignRightsProfileDefaults.generated_output_retention).toBe('minimal');
    expect(sovereignRightsProfileDefaults.generalized_learning).toBe(false);
    expect(sovereignRightsProfileDefaults.olympus_internal_intelligence).toBe(false);
    expect(sovereignRightsProfileDefaults.contributed_model_training).toBe(false);
  });

  it('standardGeneratedOutputRights: broad tenant license + governed Olympus derivation, no identifiable external disclosure', () => {
    expect(standardGeneratedOutputRights.proprietary_holder).toBe('olympus');
    expect(standardGeneratedOutputRights.tenant_license.view).toBe(true);
    expect(standardGeneratedOutputRights.tenant_license.use).toBe(true);
    expect(standardGeneratedOutputRights.tenant_license.reproduce).toBe(true);
    expect(standardGeneratedOutputRights.tenant_license.integrate).toBe(true);
    expect(standardGeneratedOutputRights.tenant_license.export).toBe(true);
    expect(standardGeneratedOutputRights.tenant_license.internal_commercial_use).toBe(true);
    expect(standardGeneratedOutputRights.olympus.retain).toBe(true);
    expect(standardGeneratedOutputRights.olympus.analyze).toBe(true);
    expect(standardGeneratedOutputRights.olympus.transform).toBe(true);
    expect(standardGeneratedOutputRights.olympus.derive).toBe(true);
    expect(standardGeneratedOutputRights.olympus.platform_improvement).toBe(true);
    expect(standardGeneratedOutputRights.olympus.internal_research).toBe(true);
    expect(standardGeneratedOutputRights.external_disclosure.identifiable).toBe(false);
    expect(standardGeneratedOutputRights.external_disclosure.generalized).toBe('governed');
    expect(standardGeneratedOutputRights.survival.tenant_exported_outputs).toBe(true);
    expect(standardGeneratedOutputRights.survival.olympus_generalized_derivatives).toBe(true);
  });

  it('standardDisclosureAuthority: internal + generalized cross-tenant allowed, identifiable external denied, generalized external governed', () => {
    expect(standardDisclosureAuthority.tenant_internal).toBe(true);
    expect(standardDisclosureAuthority.olympus_internal).toBe(true);
    expect(standardDisclosureAuthority.cross_tenant_identifiable).toBe(false);
    expect(standardDisclosureAuthority.external_identifiable).toBe(false);
    expect(standardDisclosureAuthority.generalized_cross_tenant).toBe(true);
    expect(standardDisclosureAuthority.generalized_external).toBe('governed');
  });
});
