import type { GraphNode, GraphEdge, EntityNeighborhood } from '@shiki/types';
import type { GraphCluster } from '@shiki/types';

// ---------------------------------------------------------------------------
// 18 Graph nodes — various entity types with trust/risk/anomaly scores
// ---------------------------------------------------------------------------

export const MOCK_GRAPH_NODES: GraphNode[] = [
  // Customers
  { id: 'cust-acme-001', type: 'customer', label: 'Acme Corp', trustScore: 0.74, riskScore: 0.31, anomalyScore: 0.42, metadata: { tier: 'enterprise' } },
  { id: 'cust-nebula-002', type: 'customer', label: 'Nebula Finance', trustScore: 0.91, riskScore: 0.08, anomalyScore: 0.03, metadata: { tier: 'growth' } },
  { id: 'cust-orion-003', type: 'customer', label: 'Orion DAO', trustScore: 0.86, riskScore: 0.12, anomalyScore: 0.07, metadata: { tier: 'community' } },

  // Wallets
  { id: 'wallet-0x7a3b', type: 'wallet', label: '0x7a3b...f2e1', trustScore: 0.41, riskScore: 0.68, anomalyScore: 0.72, metadata: { chain: 'ethereum', flagged: true } },
  { id: 'wallet-0xde4f', type: 'wallet', label: '0xde4f...a891', trustScore: 0.93, riskScore: 0.04, anomalyScore: 0.01, metadata: { chain: 'ethereum', verified: true } },
  { id: 'wallet-0xb19c', type: 'wallet', label: '0xb19c...3d7a', trustScore: 0.28, riskScore: 0.79, anomalyScore: 0.85, metadata: { chain: 'ethereum', flagged: true } },
  { id: 'wallet-0x4e2a', type: 'wallet', label: '0x4e2a...c045', trustScore: 0.88, riskScore: 0.07, anomalyScore: 0.04, metadata: { chain: 'polygon' } },

  // Agents
  { id: 'agent-enrich-04', type: 'agent', label: 'Enrichment Agent #04', trustScore: 0.52, riskScore: 0.55, anomalyScore: 0.81, metadata: { status: 'stuck' } },
  { id: 'agent-triage-02', type: 'agent', label: 'Triage Agent #02', trustScore: 0.94, riskScore: 0.03, anomalyScore: 0.02, metadata: { status: 'active' } },

  // Protocols
  { id: 'proto-uniswap-v3', type: 'protocol', label: 'Uniswap V3', trustScore: 0.97, riskScore: 0.02, anomalyScore: 0.01, metadata: { tvl: 3_200_000_000 } },
  { id: 'proto-aave-v3', type: 'protocol', label: 'Aave V3', trustScore: 0.95, riskScore: 0.05, anomalyScore: 0.02, metadata: { tvl: 8_700_000_000 } },

  // Contracts
  { id: 'contract-vault-01', type: 'contract', label: 'AcmeVault.sol', trustScore: 0.88, riskScore: 0.09, anomalyScore: 0.05, metadata: { proxy: true } },
  { id: 'contract-bridge-02', type: 'contract', label: 'NebulaBridge.sol', trustScore: 0.72, riskScore: 0.34, anomalyScore: 0.28, metadata: { crossChain: true } },

  // External / suspicious
  { id: 'ext-mixer-001', type: 'external', label: 'Known Mixer Contract', trustScore: 0.05, riskScore: 0.98, anomalyScore: 0.95, metadata: { blacklisted: true } },

  // Cluster representative nodes
  { id: 'cluster-c892-hub', type: 'wallet', label: 'C-892 Hub Wallet', trustScore: 0.18, riskScore: 0.89, anomalyScore: 0.93, metadata: { clusterRole: 'hub' } },
  { id: 'cluster-c892-node-a', type: 'wallet', label: 'C-892 Node A', trustScore: 0.21, riskScore: 0.82, anomalyScore: 0.88, metadata: { clusterRole: 'spoke' } },
  { id: 'cluster-c892-node-b', type: 'wallet', label: 'C-892 Node B', trustScore: 0.24, riskScore: 0.80, anomalyScore: 0.86, metadata: { clusterRole: 'spoke' } },
  { id: 'cluster-c340-hub', type: 'wallet', label: 'C-340 Institutional Hub', trustScore: 0.94, riskScore: 0.04, anomalyScore: 0.01, metadata: { clusterRole: 'hub', institutional: true } },
];

// ---------------------------------------------------------------------------
// 24 Graph edges
// ---------------------------------------------------------------------------

export const MOCK_GRAPH_EDGES: GraphEdge[] = [
  // Customer -> Wallet / Contract ownership
  { id: 'e-001', source: 'cust-acme-001', target: 'contract-vault-01', type: 'owns', weight: 1.0, label: 'owns', metadata: {} },
  { id: 'e-002', source: 'cust-acme-001', target: 'wallet-0xde4f', type: 'controls', weight: 0.9, label: 'controls', metadata: { verified: true } },
  { id: 'e-003', source: 'cust-nebula-002', target: 'contract-bridge-02', type: 'owns', weight: 1.0, label: 'owns', metadata: {} },
  { id: 'e-004', source: 'cust-nebula-002', target: 'wallet-0x4e2a', type: 'controls', weight: 0.9, label: 'controls', metadata: { verified: true } },
  { id: 'e-005', source: 'cust-orion-003', target: 'proto-uniswap-v3', type: 'uses', weight: 0.7, label: 'uses', metadata: {} },

  // Wallet -> Protocol interactions
  { id: 'e-006', source: 'wallet-0xde4f', target: 'proto-uniswap-v3', type: 'interacts', weight: 0.8, label: 'swaps on', metadata: { txCount: 127 } },
  { id: 'e-007', source: 'wallet-0xde4f', target: 'proto-aave-v3', type: 'interacts', weight: 0.6, label: 'lends on', metadata: { txCount: 43 } },
  { id: 'e-008', source: 'wallet-0x4e2a', target: 'proto-aave-v3', type: 'interacts', weight: 0.7, label: 'borrows on', metadata: { txCount: 89 } },
  { id: 'e-009', source: 'wallet-0x7a3b', target: 'proto-uniswap-v3', type: 'interacts', weight: 0.5, label: 'swaps on', metadata: { txCount: 341 } },

  // Suspicious wallet -> cluster C-892 edges
  { id: 'e-010', source: 'wallet-0x7a3b', target: 'cluster-c892-hub', type: 'transfers', weight: 0.9, label: 'transfer', metadata: { amount: '14.2 ETH', suspicious: true } },
  { id: 'e-011', source: 'wallet-0x7a3b', target: 'cluster-c892-node-a', type: 'transfers', weight: 0.7, label: 'transfer', metadata: { amount: '3.8 ETH', suspicious: true } },
  { id: 'e-012', source: 'wallet-0x7a3b', target: 'cluster-c892-node-b', type: 'transfers', weight: 0.6, label: 'transfer', metadata: { amount: '1.2 ETH', suspicious: true } },

  // Intra-cluster C-892 circular edges (wash-trading)
  { id: 'e-013', source: 'cluster-c892-hub', target: 'cluster-c892-node-a', type: 'transfers', weight: 0.95, label: 'circular', metadata: { pattern: 'wash-trading' } },
  { id: 'e-014', source: 'cluster-c892-node-a', target: 'cluster-c892-node-b', type: 'transfers', weight: 0.92, label: 'circular', metadata: { pattern: 'wash-trading' } },
  { id: 'e-015', source: 'cluster-c892-node-b', target: 'cluster-c892-hub', type: 'transfers', weight: 0.93, label: 'circular', metadata: { pattern: 'wash-trading' } },

  // Cluster -> mixer
  { id: 'e-016', source: 'cluster-c892-hub', target: 'ext-mixer-001', type: 'interacts', weight: 0.85, label: 'mixes', metadata: { suspicious: true } },

  // Additional suspicious wallet
  { id: 'e-017', source: 'wallet-0xb19c', target: 'cluster-c892-hub', type: 'transfers', weight: 0.8, label: 'transfer', metadata: { suspicious: true } },
  { id: 'e-018', source: 'wallet-0xb19c', target: 'ext-mixer-001', type: 'interacts', weight: 0.75, label: 'mixes', metadata: { suspicious: true } },

  // Institutional cluster C-340
  { id: 'e-019', source: 'cluster-c340-hub', target: 'wallet-0xde4f', type: 'transfers', weight: 0.6, label: 'custodial', metadata: { institutional: true } },
  { id: 'e-020', source: 'cluster-c340-hub', target: 'proto-aave-v3', type: 'interacts', weight: 0.5, label: 'yields', metadata: { institutional: true } },

  // Contract -> Protocol integrations
  { id: 'e-021', source: 'contract-vault-01', target: 'proto-aave-v3', type: 'integrates', weight: 0.8, label: 'yield source', metadata: {} },
  { id: 'e-022', source: 'contract-bridge-02', target: 'proto-uniswap-v3', type: 'integrates', weight: 0.6, label: 'liquidity', metadata: {} },

  // Agent -> Entity operational relationships
  { id: 'e-023', source: 'agent-enrich-04', target: 'cust-acme-001', type: 'enriches', weight: 0.4, label: 'enriching', metadata: { status: 'stuck' } },
  { id: 'e-024', source: 'agent-triage-02', target: 'wallet-0x7a3b', type: 'triages', weight: 0.7, label: 'triaging', metadata: { priority: 1 } },
];

// ---------------------------------------------------------------------------
// 3 Graph clusters
// ---------------------------------------------------------------------------

export const MOCK_GRAPH_CLUSTERS: GraphCluster[] = [
  {
    id: 'cluster-c892',
    label: 'Suspicious Cluster C-892 (Wash Trading)',
    nodeIds: ['cluster-c892-hub', 'cluster-c892-node-a', 'cluster-c892-node-b', 'wallet-0x7a3b', 'wallet-0xb19c'],
    centroidNodeId: 'cluster-c892-hub',
    size: 47,
    avgTrustScore: 0.22,
    avgRiskScore: 0.85,
    anomalyCount: 12,
  },
  {
    id: 'cluster-c340',
    label: 'Institutional Cluster C-340',
    nodeIds: ['cluster-c340-hub', 'wallet-0xde4f'],
    centroidNodeId: 'cluster-c340-hub',
    size: 23,
    avgTrustScore: 0.92,
    avgRiskScore: 0.05,
    anomalyCount: 0,
  },
  {
    id: 'cluster-defi-core',
    label: 'DeFi Core Protocols',
    nodeIds: ['proto-uniswap-v3', 'proto-aave-v3', 'contract-vault-01', 'contract-bridge-02'],
    centroidNodeId: 'proto-uniswap-v3',
    size: 4,
    avgTrustScore: 0.88,
    avgRiskScore: 0.13,
    anomalyCount: 1,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function getMockGraphData(): {
  nodes: GraphNode[];
  edges: GraphEdge[];
  clusters: GraphCluster[];
} {
  return {
    nodes: [...MOCK_GRAPH_NODES],
    edges: [...MOCK_GRAPH_EDGES],
    clusters: [...MOCK_GRAPH_CLUSTERS],
  };
}

export function getMockEntityNeighborhood(entityId: string): EntityNeighborhood {
  const relevantEdges = MOCK_GRAPH_EDGES.filter(
    (e) => e.source === entityId || e.target === entityId,
  );
  const neighborIds = new Set<string>();
  for (const edge of relevantEdges) {
    if (edge.source !== entityId) neighborIds.add(edge.source);
    if (edge.target !== entityId) neighborIds.add(edge.target);
  }
  const neighborNodes = MOCK_GRAPH_NODES.filter((n) => neighborIds.has(n.id));
  const centerNode = MOCK_GRAPH_NODES.find((n) => n.id === entityId);
  const nodes = centerNode ? [centerNode, ...neighborNodes] : neighborNodes;

  return { entityId, nodes, edges: relevantEdges };
}
