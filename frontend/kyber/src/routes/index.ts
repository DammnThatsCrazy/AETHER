// Route definitions for Kyber
export const ROUTES = {
  MISSION: '/mission',
  LIVE: '/live',
  NOESIS: '/noesis',
  ENTITIES: '/entities',
  ENTITY_DETAIL: '/entities/:type/:id',
  PROFILE360_DETAIL: '/profile360/:type/:id',
  COMMAND: '/command',
  DIAGNOSTICS: '/diagnostics',
  REVIEW: '/review',
  REVIEW_BATCH: '/review/:batchId',
  LAB: '/lab',
  CIS: '/cis',
  CIS_MUTATIONS: '/cis/mutations',
  CIS_FORENSICS: '/cis/forensics/:nodeId',
  CIS_RETRIEVAL: '/cis/retrieval',
  CIS_DRIFT: '/cis/drift',
} as const;

export function entityDetailPath(type: string, id: string): string {
  return `/entities/${type}/${id}`;
}

export function reviewBatchPath(batchId: string): string {
  return `/review/${batchId}`;
}

export function profile360Path(type: string, id: string): string {
  return `/profile360/${type}/${id}`;
}

export function cisForensicsPath(nodeId: string): string {
  return `/cis/forensics/${nodeId}`;
}
