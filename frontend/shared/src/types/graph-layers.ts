export type RelationshipLayer = 'H2H' | 'H2A' | 'A2H' | 'A2A';

export const RELATIONSHIP_LAYERS = ['H2H', 'H2A', 'A2H', 'A2A'] as const satisfies readonly RelationshipLayer[];

export const LAYER_COUNT = RELATIONSHIP_LAYERS.length;

export const LAYER_DESCRIPTIONS: Record<RelationshipLayer, { label: string; description: string }> = {
  H2H: {
    label: 'Human-to-Human',
    description: 'Relationships between individual humans: sessions, social links, identity merges, referrals.',
  },
  H2A: {
    label: 'Human-to-Agent',
    description: 'Humans delegating work to or hiring AI agents: delegation, ownership, configuration.',
  },
  A2H: {
    label: 'Agent-to-Human',
    description: 'Agents acting on behalf of or communicating with humans: notifications, recommendations, deliveries, escalations.',
  },
  A2A: {
    label: 'Agent-to-Agent',
    description: 'Relationships between AI agents: sub-contracting, payments, coordination, collaboration.',
  },
};

export const EDGE_LAYER_MAP: Record<string, RelationshipLayer> = {
  // H2H
  HAS_SESSION: 'H2H',
  RESOLVED_AS: 'H2H',
  REFERRED_BY: 'H2H',
  CONNECTED_TO: 'H2H',
  FOLLOWS: 'H2H',
  // H2A
  DELEGATES: 'H2A',
  OWNS: 'H2A',
  HIRED: 'H2A',
  CONFIGURES: 'H2A',
  AUTHORIZES: 'H2A',
  // A2H
  NOTIFIES: 'A2H',
  RECOMMENDS: 'A2H',
  DELIVERS_TO: 'A2H',
  ESCALATES_TO: 'A2H',
  ACTS_ON_BEHALF_OF: 'A2H',
  REPORTS_TO: 'A2H',
  // A2A
  PAYS: 'A2A',
  COORDINATES_WITH: 'A2A',
  SUB_CONTRACTS: 'A2A',
  COLLABORATES: 'A2A',
};

export function classifyEdgeType(edgeType: string): RelationshipLayer | null {
  return EDGE_LAYER_MAP[edgeType] ?? null;
}

export function countEdgesByLayer(edges: { type: string }[]): Record<RelationshipLayer, number> {
  const counts: Record<RelationshipLayer, number> = { H2H: 0, H2A: 0, A2H: 0, A2A: 0 };
  for (const edge of edges) {
    const layer = classifyEdgeType(edge.type);
    if (layer) counts[layer]++;
  }
  return counts;
}
