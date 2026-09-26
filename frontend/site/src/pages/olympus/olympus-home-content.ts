/** Copy and data for Olympus Home (Olympus Home.dc.html). */
import type { Accent } from '@site/site/palette';

export type HomeTab = 'company' | 'principles' | 'research' | 'contact';

export const HOME_TABS: Array<{ id: HomeTab; glyph: string; label: string; accent: Accent }> = [
  { id: 'company', glyph: '◈', label: 'Company', accent: 'cobalt' },
  { id: 'principles', glyph: '✓', label: 'Principles', accent: 'sage' },
  { id: 'research', glyph: '⚗', label: 'Research', accent: 'steel' },
  { id: 'contact', glyph: '✉', label: 'Contact', accent: 'ochre' },
];

export function isHomeTab(value: string): value is HomeTab {
  return HOME_TABS.some((t) => t.id === value);
}

export const ACTOR_CHIPS: Array<{ label: string; body: string; accent: Accent }> = [
  { label: '● humans', body: 'people and the teams they form', accent: 'cobalt' },
  { label: '⬡ autonomous agents', body: 'software acting on someone’s behalf', accent: 'ochre' },
  { label: '◈ organizations', body: 'companies, partners, syndicates', accent: 'sage' },
  { label: '↑ economic activity', body: 'value, payments, and settlement', accent: 'solar' },
];

/** `detail` is what the principle means for Aether (Olympus Principles). */
export const PRINCIPLES: Array<{ numeral: string; text: string; detail: string; accent: Accent }> = [
  { numeral: 'I', text: 'Operational intelligence should augment human decision-making, not replace it.', detail: 'Aether recommends, identifies, and explains. People decide.', accent: 'cobalt' },
  { numeral: 'II', text: 'Governed intelligence systems must remain explainable, auditable, and accountable.', detail: 'Every inference shows its evidence and confidence. Every decision keeps a trail.', accent: 'sage' },
  { numeral: 'III', text: 'Human agency remains sovereign over autonomous operational systems.', detail: 'Critical actions above set thresholds wait for a person’s authorization.', accent: 'ochre' },
  { numeral: 'IV', text: 'Intelligence infrastructure must operate within lawful, governed, and consent-aware boundaries.', detail: 'Capture is gated on consent. Tenants never share intelligence.', accent: 'steel' },
  { numeral: 'V', text: 'Operational trust is foundational infrastructure.', detail: 'Trust is designed into the data model, not added as a setting.', accent: 'solar' },
];

export interface ResearchArea {
  id: string;
  glyph: string;
  title: string;
  body: string;
  /** One-line question for the Olympus Home card. */
  question: string;
  /** The open questions listed on the Research page. */
  questions: string[];
  accent: Accent;
}

export const RESEARCH_AREAS: ResearchArea[] = [
  { id: 'identity', glyph: '⬡', title: 'Identity continuity', body: 'Tenant-scoped relationships across systems, without treating one source as universal truth.', question: 'When does evidence justify joining two records — and how do you undo it?', questions: ['When does evidence justify joining two records?', 'How is a join undone when the evidence changes?'], accent: 'cobalt' },
  { id: 'temporal', glyph: '◉', title: 'Temporal journeys', body: 'Transitions and sequences over time, not isolated events.', question: 'How do journeys pause, resume, and continue across devices and agents?', questions: ['How do journeys pause, resume, and continue across devices and agents?'], accent: 'sage' },
  { id: 'attribution', glyph: '→', title: 'Evidence-backed attribution', body: 'Touchpoints to value, with assumptions and uncertainty visible.', question: 'How much credit does an agent deserve for an outcome a person approved?', questions: ['How much credit does an agent deserve for an outcome a person approved?'], accent: 'solar' },
  { id: 'agents', glyph: '↔', title: 'Human and agent coordination', body: 'Observable handoffs between people and agents, with authority preserved.', question: 'How is delegated authority represented, scoped, and revoked?', questions: ['How is delegated authority represented, scoped, and revoked?'], accent: 'ochre' },
  { id: 'economic', glyph: '↑', title: 'Economic perspective', body: 'Value flows reasoned about without stripping their native meaning.', question: 'How do payments, settlement, and ledger effects join the relationship graph?', questions: ['How do payments, settlement, and ledger effects join the relationship graph?'], accent: 'steel' },
  { id: 'assurance', glyph: '✓', title: 'High-assurance deployment', body: 'Sovereign, on-premise, and air-gapped deployments where confidence must be earned.', question: 'What evidence proves a boundary held?', questions: ['What evidence proves a boundary held?'], accent: 'ember' },
];

export const CONTACT_ROUTES: Array<{ type: string; glyph: string; title: string; body: string; cta: string; accent: Accent }> = [
  { type: 'pilot', glyph: '→', title: 'Start a pilot', body: 'Bring one relationship question and the systems that hold the evidence.', cta: 'Request a pilot', accent: 'sage' },
  { type: 'security', glyph: '✓', title: 'Security review', body: 'Architecture, tenant scope, consent, retention, and deployment options.', cta: 'Request a review', accent: 'ember' },
  { type: 'research', glyph: '⚗', title: 'Research', body: 'Collaborate on identity, attribution, or agent coordination.', cta: 'Discuss research', accent: 'steel' },
  { type: 'proof', glyph: '◉', title: 'Proof partner', body: 'Document a governed loop with your own data and baseline.', cta: 'Become a partner', accent: 'solar' },
  { type: 'product', glyph: '◈', title: 'Product questions', body: 'What Aether does today and what is on the way.', cta: 'Ask a question', accent: 'cobalt' },
];

export interface UnifyGroup {
  id: string;
  glyph: string;
  label: string;
  accent: Accent;
  title: string;
  body: string;
  source: string;
  items: Array<[name: string, detail: string]>;
}

export const UNIFY_GROUPS: UnifyGroup[] = [
  {
    id: 'entities', glyph: '⬡', label: 'Entities', accent: 'cobalt', title: 'Every operationally relevant actor',
    body: 'An entity is any actor that matters in a system. Each one resolves into a profile with its own timeline, graph, and intelligence.',
    source: 'positioning doc · Aether Entities',
    items: [['Humans', 'people and users'], ['Organizations', 'companies, accounts, households'], ['AI agents', 'systems that plan and act'], ['Systems', 'services and applications'], ['Devices', 'browsers, phones, hardware'], ['Economic identities', 'wallets, payment accounts'], ['Autonomous processes', 'scheduled and self-running jobs'], ['Campaigns', 'marketing entities with touchpoints']],
  },
  {
    id: 'relationships', glyph: '↔', label: 'Relationships', accent: 'sage', title: 'How entities relate',
    body: 'The four relationship kinds between people and agents, plus the structures they form over time.',
    source: 'positioning doc · Aether Graph',
    items: [['Human → human', 'collaboration, approvals'], ['Human → agent', 'delegation, review'], ['Agent → agent', 'orchestration, handoff'], ['Agent → human', 'escalation, decisions'], ['Syndicates', 'clusters of humans and agents'], ['Shared devices and wallets', 'identity edges'], ['Referral chains', 'who brought whom'], ['Co-purchasers', 'commerce edges']],
  },
  {
    id: 'activity', glyph: '◉', label: 'Activity and events', accent: 'ochre', title: 'What happened, and when',
    body: 'About 400 canonical event types across two dozen families, all on one contract so every source speaks the same language.',
    source: 'repo · EVENT_REGISTRY',
    items: [['Interaction', 'page, track, conversion'], ['Identity', 'identify, resolve'], ['Consent', 'grants and revocations'], ['Commerce', 'product, cart, checkout, order'], ['Payments', 'payment, refund, settlement'], ['Journeys', 'start, checkpoint, complete, abandon'], ['Agents', 'task, tool call, outcome'], ['Communications', 'messages and deliveries'], ['Web3', 'wallet, transaction']],
  },
  {
    id: 'intelligence', glyph: '◈', label: 'Intelligence', accent: 'solar', title: 'What the graph lets you understand',
    body: 'The operational intelligence Aether derives from evidence — each result with its confidence and source.',
    source: 'positioning doc · Aether Intelligence',
    items: [['Behavioral patterns', ''], ['Attribution pathways', ''], ['Relationship clusters', ''], ['Fraud relationships', ''], ['Operational risk', ''], ['Customer journeys', ''], ['High-value users', ''], ['Cross-platform identity', '']],
  },
  {
    id: 'connectors', glyph: '⚙', label: 'Connected systems', accent: 'steel', title: '13 managed connectors, plus any system you can reach',
    body: 'Managed connectors pull or receive events from the tools a business already runs and normalize them into the Aether envelope. Anything else connects through a signed webhook, the feed API, or an import.',
    source: 'repo · docs/CONNECTORS.md',
    items: [['HubSpot', 'CRM'], ['Salesforce', 'CRM'], ['Shopify', 'commerce'], ['Stripe', 'billing'], ['Klaviyo', 'marketing'], ['Segment', 'analytics'], ['PostHog', 'analytics'], ['GA4', 'analytics'], ['Zendesk', 'support'], ['Intercom', 'support'], ['Jira', 'project · outbound'], ['Linear', 'project · outbound'], ['Slack', 'messaging · outbound'], ['Signed webhook', 'any system'], ['Feed API', 'any backend'], ['File import', 'CSV · JSON · JSONL']],
  },
  {
    id: 'paths', glyph: '→', label: 'Ways in and out', accent: 'ember', title: 'Many ways in, one governed way out',
    body: 'Every path lands in the same Bronze record with source, consent, and tenant attached. Exports are tenant-forced and redacted.',
    source: 'repo · DATA-INGESTION-PATHS · data-exchange',
    items: [['Web SDK', '@aether/web'], ['iOS SDK', 'AetherSDK'], ['Android SDK', 'sdk-android'], ['React Native SDK', '@aether/react-native'], ['Server events', '/v1/ingest/feed'], ['Connector sync', 'pull'], ['Webhooks', 'push · HMAC'], ['Imports', 'CSV, JSON, JSONL'], ['Exports', '/v1/data-exchange'], ['Audit exports', '/v1/audit']],
  },
  {
    id: 'governance', glyph: '✓', label: 'Governance', accent: 'sage', title: 'What keeps it accountable',
    body: 'Consent, policy, explainability, and human authority apply to every connection above.',
    source: 'positioning doc · Aether Governance',
    items: [['Consent systems', 'purpose per event'], ['Policy enforcement', ''], ['Explainability', ''], ['Auditability', ''], ['Access controls', 'write, read, admin keys'], ['Tenant isolation', ''], ['Human approval', 'above set thresholds'], ['Deletion', 'raw data removed on request']],
  },
];

/** Glyphs for connector entries that are not a vendor mark. */
export const GENERIC_CONNECTOR_GLYPHS: Record<string, string> = {
  'Signed webhook': '↯',
  'Feed API': '≡',
  'File import': '⇪',
};
