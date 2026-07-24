export {
  useAccessInventory,
  useCapabilityCatalog,
  useCapabilityRiskFindings,
  useAgentProfiles,
  useAgentProfile,
  useAgentBlastRadius,
  useCapabilityAuthorizations,
  fetchAccessGraphSummary,
  fetchCapabilityCatalog,
  fetchRiskFindings,
  fetchAgentProfiles,
  fetchAgentProfile,
  fetchAgentBlastRadius,
  fetchCapabilityAuthorizations,
} from './use-agent-access';

export type {
  Capability,
  AccessGraphSummary,
  RiskFinding,
  RiskFindingsResult,
  ReachedCapability,
  BlastRadius,
  AgentProfile,
  AgentProfileIndex,
  AgentProfileIndexEntry,
  CapabilityAuthorization,
} from './use-agent-access';
