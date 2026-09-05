/**
 * DO NOT EDIT — generated from packages/shared/contracts/lens-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const lensRegistryContractVersion = '1.0.0' as const;

/** Lens kinds a lens may be (sorted). */
export const lensRegistryKinds = ['base', 'overlay'] as const;
export type LensRegistryKind = typeof lensRegistryKinds[number];

/** Registered projection-engine lenses (sorted). */
export const lensIds = [
  'agent',
  'attribution',
  'campaign',
  'communication',
  'consent',
  'data_quality',
  'deployment',
  'economic',
  'engagementfi',
  'episode',
  'evidence',
  'execution',
  'fraud',
  'geographic',
  'infrastructure',
  'journey',
  'narrative',
  'operational',
  'outcome',
  'payment',
  'policy',
  'population',
  'relationship',
  'risk',
  'security',
  'socialfi',
  'source',
  'standard',
  'temporal',
  'trust',
  'wallet',
] as const;
export type LensId = typeof lensIds[number];

/** One registered projection-engine lens (mirrors the registry schema). */
export interface LensDescriptor {
  id: LensId;
  displayName: string;
  kind: LensRegistryKind;
  baseLens: LensId | null;
  description: string;
  domain: string;
  applicableSubjectKinds: readonly string[];
  temporalModes: readonly string[];
  default: boolean;
}

export const lensDefinitions: Record<LensId, LensDescriptor> = {
  agent: {
    id: 'agent',
    displayName: 'Agent',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through agentic structure — agents, access, tool use, executions. Composes with the agent360 / execution360 projections.',
    domain: 'agentic',
    applicableSubjectKinds: ['agent', 'entity'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  attribution: {
    id: 'attribution',
    displayName: 'Attribution',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views conversions through attribution — credits, models, touchpoint contributions. Composes with the outcome360 measurement engine.',
    domain: 'attribution',
    applicableSubjectKinds: ['campaign', 'episode'],
    temporalModes: ['compare', 'relative', 'window'],
    default: false
  },
  campaign: {
    id: 'campaign',
    displayName: 'Campaign',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds campaign structure — campaign facts, touchpoints, quality, source mapping. Composes with the campaign360 projection.',
    domain: 'campaign',
    applicableSubjectKinds: ['campaign', 'episode', 'population', 'source'],
    temporalModes: ['compare', 'relative', 'window'],
    default: false
  },
  communication: {
    id: 'communication',
    displayName: 'Communication',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through outbound communication — channels, messages, delivery, engagement. Composes with the communication360 projection.',
    domain: 'communication',
    applicableSubjectKinds: ['campaign', 'episode', 'source'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  consent: {
    id: 'consent',
    displayName: 'Consent',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through consent — consent state, historical consent evaluation, permitted purposes. Composes with policy evaluation; never leaks a use outside consented purposes.',
    domain: 'consent',
    applicableSubjectKinds: ['entity', 'population'],
    temporalModes: ['as_of', 'compare', 'window'],
    default: false
  },
  data_quality: {
    id: 'data_quality',
    displayName: 'Data Quality',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through data quality — completeness, freshness, confidence, limitations. A data-quality section always accompanies the sections it qualifies.',
    domain: 'data_quality',
    applicableSubjectKinds: ['campaign', 'cluster', 'connection', 'entity', 'population', 'source'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  deployment: {
    id: 'deployment',
    displayName: 'Deployment',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds deployment structure — deployments, rollouts, environments, target states. Composes with the infrastructure360 projection.',
    domain: 'deployment',
    applicableSubjectKinds: ['deployment', 'entity', 'infrastructure'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  economic: {
    id: 'economic',
    displayName: 'Economic',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through economic value — flows, positions, obligations, allocations, settlements, cost/margin/exposure. Composes with the economic360 projection; never sums mixed currencies.',
    domain: 'economic',
    applicableSubjectKinds: ['campaign', 'entity', 'episode', 'population', 'source'],
    temporalModes: ['compare', 'relative', 'window'],
    default: false
  },
  engagementfi: {
    id: 'engagementfi',
    displayName: 'EngagementFi',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds engagement mechanics — social interactions, content and communities, and the relationship and incentive structure that drives or discounts that engagement. Surfaces the M1 filter-field categories social, relationship, incentive, source and evidence over the social360 projection, gated so correlated observations are never counted as independent evidence.',
    domain: 'engagementfi',
    applicableSubjectKinds: ['campaign', 'entity', 'relationship', 'source'],
    temporalModes: ['relative', 'window'],
    default: false
  },
  episode: {
    id: 'episode',
    displayName: 'Episode',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject as a sequence of episodes — events, boundaries, continuity, arc structure.',
    domain: 'episode',
    applicableSubjectKinds: ['campaign', 'entity', 'episode'],
    temporalModes: ['relative', 'window'],
    default: false
  },
  evidence: {
    id: 'evidence',
    displayName: 'Evidence',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds evidence — evidence refs, provenance, grounding of every claim. Every claim rendered under this lens must carry evidence refs or be marked ungrounded.',
    domain: 'evidence',
    applicableSubjectKinds: ['campaign', 'cluster', 'connection', 'entity', 'episode', 'relationship', 'source'],
    temporalModes: ['as_of', 'compare', 'window'],
    default: false
  },
  execution: {
    id: 'execution',
    displayName: 'Execution',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds execution — actions taken, jobs, flows, resources consumed, outcomes produced. Composes with the execution360 projection.',
    domain: 'execution',
    applicableSubjectKinds: ['agent', 'entity', 'episode'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  fraud: {
    id: 'fraud',
    displayName: 'Fraud',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds fraudulent structure — fraud synthesis, graph motifs, anomaly concentration. Composes with the fraud360 projection.',
    domain: 'fraud',
    applicableSubjectKinds: ['agent', 'entity', 'relationship'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  geographic: {
    id: 'geographic',
    displayName: 'Geographic',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views a subject through place — locations, regions, geo observations, movement. Composes with the geographic360 projection\'s context-capsule semantics.',
    domain: 'spatial',
    applicableSubjectKinds: ['entity', 'population', 'source'],
    temporalModes: ['compare', 'relative', 'window'],
    default: false
  },
  infrastructure: {
    id: 'infrastructure',
    displayName: 'Infrastructure',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through infrastructure — entities, deployments, state, relationships among infrastructure facts. Composes with the infrastructure360 projection (read-only).',
    domain: 'infrastructure',
    applicableSubjectKinds: ['deployment', 'entity', 'infrastructure'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  journey: {
    id: 'journey',
    displayName: 'Journey',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds journey structure — touchpoints, stages, path, completion. Composes with the episode360 / outcome360 journey semantics.',
    domain: 'journey',
    applicableSubjectKinds: ['campaign', 'entity', 'episode'],
    temporalModes: ['compare', 'relative', 'window'],
    default: false
  },
  narrative: {
    id: 'narrative',
    displayName: 'Narrative',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views a subject through narrative structure — narrative refs, the relationship arcs and evidence that ground them, and the fidelity-aware paths over which narrative propagates. Surfaces the M1 filter-field categories narrative, evidence, source, path, social and relationship over the social360 projection; every rendered claim resolves to evidence or is marked ungrounded.',
    domain: 'narrative',
    applicableSubjectKinds: ['entity', 'episode', 'relationship', 'source'],
    temporalModes: ['relative', 'window'],
    default: false
  },
  operational: {
    id: 'operational',
    displayName: 'Operational',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through operations — operational health, coverage, workbench state. Composes with the operational_workbench projections.',
    domain: 'operational',
    applicableSubjectKinds: ['cluster', 'connection', 'source'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  outcome: {
    id: 'outcome',
    displayName: 'Outcome',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through outcomes — state, finality, transitions, chains, journey completion. Composes with the outcome360 projection.',
    domain: 'outcome',
    applicableSubjectKinds: ['campaign', 'entity', 'episode', 'population'],
    temporalModes: ['compare', 'relative', 'window'],
    default: false
  },
  payment: {
    id: 'payment',
    displayName: 'Payment',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds payment structure — payments, settlements, refunds, obligations. Composes with the economic360 payment authorities.',
    domain: 'payment',
    applicableSubjectKinds: ['entity', 'source'],
    temporalModes: ['compare', 'relative', 'window'],
    default: false
  },
  policy: {
    id: 'policy',
    displayName: 'Policy',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through policy — governance constraints, export class, distillation risk, entitlements. A policy-supressed lens set drops the affected sections rather than rendering them.',
    domain: 'policy',
    applicableSubjectKinds: ['campaign', 'entity', 'population', 'source'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  population: {
    id: 'population',
    displayName: 'Population',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views a subject as a member of a population or cohort — definitions, membership, clustering, comparison baselines.',
    domain: 'population',
    applicableSubjectKinds: ['cluster', 'entity', 'population'],
    temporalModes: ['relative', 'window'],
    default: false
  },
  relationship: {
    id: 'relationship',
    displayName: 'Relationship',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds the relationship graph — connections, edges, hop structure, graph motifs. Composes with the relationship360 projection.',
    domain: 'relationship',
    applicableSubjectKinds: ['entity', 'relationship'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  risk: {
    id: 'risk',
    displayName: 'Risk',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through risk — risk outputs, model governance, capability risk, exposure. Composes with the risk360 projection.',
    domain: 'risk',
    applicableSubjectKinds: ['cluster', 'entity', 'population', 'relationship'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  security: {
    id: 'security',
    displayName: 'Security',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through security posture — security state, exposure, hardening status. Composes with the infrastructure360 security authorities.',
    domain: 'security',
    applicableSubjectKinds: ['deployment', 'entity', 'infrastructure'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  socialfi: {
    id: 'socialfi',
    displayName: 'SocialFi',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views a subject through its social-financial structure — cross-provider social identity, account and connection types, communities, interactions, and the incentive context that exposure creates. Surfaces the M1 filter-field categories social, relationship, incentive, source and evidence over the social360 projection. Absent incentive evidence is never rendered as organic and an unavailable social metric is never rendered as zero (unknown is a state, zero is a measurement).',
    domain: 'socialfi',
    applicableSubjectKinds: ['connection', 'entity', 'relationship', 'source'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  source: {
    id: 'source',
    displayName: 'Source',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through its sources — provider registry, source provenance, ingestion health, schema, coverage. Composes with the source360 projection.',
    domain: 'source',
    applicableSubjectKinds: ['connection', 'source'],
    temporalModes: ['relative', 'window'],
    default: false
  },
  standard: {
    id: 'standard',
    displayName: 'Standard',
    kind: 'base',
    baseLens: null,
    description: 'The default lens: the plain, unadorned projection over canonical Aether truth — identity, relationship facts, graph, evidence, temporal, measurement. The identity element of lens composition; composing any overlay onto Standard leaves Standard intact.',
    domain: 'general',
    applicableSubjectKinds: ['agent', 'campaign', 'cluster', 'connection', 'entity', 'episode', 'population', 'relationship', 'source'],
    temporalModes: ['as_of', 'compare', 'relative', 'window'],
    default: true
  },
  temporal: {
    id: 'temporal',
    displayName: 'Temporal',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Foregrounds temporal structure — state over time, transitions, validity, bitemporal history, correction deltas. When composed with COMPARE/CORRECTION_DIFF modes it is the dominant lens for change detection.',
    domain: 'temporal',
    applicableSubjectKinds: ['campaign', 'entity', 'episode', 'relationship', 'source'],
    temporalModes: ['as_of', 'compare', 'relative', 'window'],
    default: false
  },
  trust: {
    id: 'trust',
    displayName: 'Trust',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through trust — reputation signals, provenance of the underlying truth, confidence of sources.',
    domain: 'trust',
    applicableSubjectKinds: ['entity', 'relationship', 'source'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
  wallet: {
    id: 'wallet',
    displayName: 'Wallet',
    kind: 'overlay',
    baseLens: 'standard',
    description: 'Views the subject through wallet structure — wallet identities, balances, on-chain positions. Composes with the economic360 wallet/payment authorities.',
    domain: 'wallet',
    applicableSubjectKinds: ['entity', 'source'],
    temporalModes: ['as_of', 'relative', 'window'],
    default: false
  },
};
