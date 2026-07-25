// Dataset module for `demo-live` builds: a shared non-production backend
// serves the synthetic tenant, so nothing synthetic is compiled in. Vite
// aliases `@demo/data/dataset` here, which is why `./fixtures` is unreachable
// from a `demo-live` bundle.
//
// The `import type` below is erased at build time (it never becomes a runtime
// import); it exists only so the two dataset modules cannot drift apart.
import type * as Fixtures from './fixtures';

export const DEMO_TENANT: typeof Fixtures.DEMO_TENANT = { tenant_id: '', name: '', plan: '' };
export const INGESTION_PATHS: typeof Fixtures.INGESTION_PATHS = [];
export const PROFILE360: typeof Fixtures.PROFILE360 = {
  entity: '',
  signals: 0,
  identities: [],
  relationships: 0,
  confidence: 0,
};
export const RECOMMENDATIONS: typeof Fixtures.RECOMMENDATIONS = [];
export const OODA: typeof Fixtures.OODA = [];
export const DECISIONS: typeof Fixtures.DECISIONS = [];
export const DISPATCHES: typeof Fixtures.DISPATCHES = [];
export const OUTCOMES: typeof Fixtures.OUTCOMES = [];
export const PLAYBOOKS: typeof Fixtures.PLAYBOOKS = [];
export const VALUE_REVIEW: typeof Fixtures.VALUE_REVIEW = {
  retained_revenue: 0,
  expansion_revenue: 0,
  avoided_loss: 0,
  total: 0,
};
export const DATA_QUALITY: typeof Fixtures.DATA_QUALITY = {
  overall: 0,
  status: 'unknown',
  dimensions: { event: 0, identity: 0, graph: 0, recommendation: 0, outcome: 0 },
};
export const KYBER_VIEW: typeof Fixtures.KYBER_VIEW = {
  tenant: '',
  health_score: 0,
  expansion_score: 0,
  renewal_risk: 'unknown',
  recommendations_acted: 0,
  value_created_total: 0,
  intelligence_quality: 0,
};
