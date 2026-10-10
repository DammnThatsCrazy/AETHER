import type {
  AlignmentDecision,
  ComparisonFindingDetail,
  ComparisonRunDetail,
} from './comparison-api';

const COMPARABLE = new Set(['aligned', 'aligned_after_conversion', 'partially_aligned']);

function decisionFor(
  finding: ComparisonFindingDetail,
  run: ComparisonRunDetail,
): AlignmentDecision | undefined {
  return run.alignment_decisions?.find(decision => decision.dimension === finding.dimension);
}

export interface AssessedFinding {
  finding: ComparisonFindingDetail;
  unit: string | null;
  comparable: boolean;
  missingInputs: string[];
}

/**
 * Values are displayable only when the run proves aligned units and the
 * finding carries evidence provenance. Missing metadata downgrades the row;
 * it never silently becomes a comparable zero or unitless number.
 */
export function assessFinding(
  finding: ComparisonFindingDetail,
  run: ComparisonRunDetail,
): AssessedFinding {
  const decision = decisionFor(finding, run);
  const pair = decision?.pairs.find(candidate => candidate.name === finding.metric);
  const missingInputs: string[] = [];
  if (!decision || !COMPARABLE.has(decision.outcome)) {
    missingInputs.push(`alignment:${decision?.outcome ?? 'missing'}`);
  }
  if (!pair?.unit) missingInputs.push('unit');
  if (!finding.evidence_basis) missingInputs.push('provenance');
  if (finding.confidence == null) missingInputs.push('confidence');
  if (finding.materiality == null) missingInputs.push('materiality');
  if (!finding.causal_claim) missingInputs.push('causal_claim');
  return {
    finding,
    unit: pair?.unit ?? null,
    comparable: missingInputs.length === 0,
    missingInputs,
  };
}
