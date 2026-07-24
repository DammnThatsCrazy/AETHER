// Canonical traffic-source presentation helpers.
//
// The vocabulary (SourceClass, ProofLevel, EntryMethod) is generated from
// packages/shared/contracts/traffic-source-registry.json — the UI never
// invents labels. The honest fallback is "Direct / Unknown": the platform
// never claims a user "typed a URL", it only reports that no referral
// evidence exists.

import {
  SOURCE_CLASS_DEFAULTS,
  canonicalSourceClass,
  type SourceClass,
} from '@aether/shared/traffic-source';

/**
 * Customer-facing label for a (possibly legacy) source_class value.
 * Legacy "direct" normalizes to direct_unknown → "Direct / Unknown".
 * Unknown future values fall back to the raw value rather than a wrong claim.
 */
export function sourceClassLabel(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const canonical = canonicalSourceClass(String(value));
  const defaults = SOURCE_CLASS_DEFAULTS[canonical as SourceClass];
  return defaults?.label ?? String(value);
}

/** Human form of registry snake_case values (proof levels, entry methods). */
export function humanizeRegistryValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  return String(value).replace(/_/g, ' ');
}

/**
 * Compact evidence summary for a touchpoint row tooltip: entry method, proof
 * level, verification, and any classifier conflicts — only fields that are
 * actually present (all optional on older rows).
 */
export function touchpointEvidenceSummary(tp: Record<string, unknown>): string {
  const parts: string[] = [];
  if (tp.entry_method) parts.push(`Entry: ${humanizeRegistryValue(tp.entry_method)}`);
  if (tp.proof_level) parts.push(`Proof: ${humanizeRegistryValue(tp.proof_level)}`);
  if (tp.verification_level) {
    parts.push(`Verification: ${humanizeRegistryValue(tp.verification_level)}`);
  }
  const conflicts = tp.classification_conflicts ?? tp.conflicts;
  if (Array.isArray(conflicts) && conflicts.length > 0) {
    parts.push(`Conflicts: ${conflicts.map(String).join('; ')}`);
  }
  return parts.join(' · ');
}
