// Deterministic server-shaped 360 frame for adapter tests. The adapter must
// return exactly this object: partial, unknown, degraded, and stale slot states
// and every evidence/limitation field are the server's, not the adapter's.
export function frameFor(body) {
  return {
    surfaceId: body.surfaceId,
    tenantId: 'tenant-from-auth',
    subject: body.subject,
    surfaceCatalogVersion: '0.2.0',
    contractVersion: '1.0.0',
    generatedAt: '2026-10-29T12:00:00Z',
    state: 'partial',
    slots: [
      {
        id: 'identity',
        requirement: 'required',
        state: 'available',
        content: { display: 'Example agent' },
        provenance: [{ projectionId: 'agent360', tenantId: 'tenant-from-auth', evidenceRefs: ['ev-1'] }],
        evidenceRefs: ['ev-1'],
        policyDisposition: { state: 'allowed' },
        limitations: [],
        reasonCodes: [],
      },
      {
        id: 'tool_usage',
        requirement: 'optional',
        state: 'unknown',
        policyDisposition: { state: 'allowed' },
        limitations: ['no_observation_source_bound'],
        reasonCodes: ['projection_unbound'],
      },
      {
        id: 'risk_summary',
        requirement: 'optional',
        state: 'degraded',
        content: { level: 'indeterminate' },
        evidenceRefs: ['ev-2'],
        provenance: [{ projectionId: 'risk360', tenantId: 'tenant-from-auth', evidenceRefs: ['ev-2'] }],
        policyDisposition: { state: 'allowed' },
        limitations: ['source_stale'],
        reasonCodes: ['freshness_exceeded'],
      },
      {
        id: 'capabilities',
        requirement: 'optional',
        state: 'suppressed',
        policyDisposition: { state: 'denied', reasonCodes: ['scope_missing'] },
        limitations: [],
        reasonCodes: ['policy_denied'],
      },
    ],
    degradation: { degraded: true, reasonCodes: ['freshness_exceeded'] },
    warnings: ['partial_frame'],
    ownsCanonicalTruth: false,
  };
}
