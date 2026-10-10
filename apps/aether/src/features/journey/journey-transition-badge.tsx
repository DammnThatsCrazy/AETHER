import type { FC } from 'react';

const TRANSITION_LABELS: Record<string, string> = {
  same_session: 'Same session',
  new_session: 'New session',
  cross_device: 'Cross-device',
  cross_browser: 'Cross-browser',
  cross_domain: 'Cross-domain',
  web_to_mobile: 'Web → Mobile',
  mobile_to_web: 'Mobile → Web',
  web_to_dapp: 'Web → dApp',
  dapp_to_web: 'dApp → Web',
  web2_to_web3: 'Web2 → Web3',
  web3_to_web2: 'Web3 → Web2',
  wallet_connected: 'Wallet connected',
  wallet_disconnected: 'Wallet disconnected',
  cross_wallet: 'Cross-wallet',
  cross_chain: 'Cross-chain',
  cross_protocol: 'Cross-protocol',
  human_to_agent: 'Human → Agent',
  agent_to_human: 'Agent → Human',
  agent_to_agent: 'Agent handoff',
  campaign_to_owned_surface: 'Campaign → Owned',
  owned_surface_to_conversion: 'Owned → Conversion',
  identity_resolved: 'Identity resolved',
  identity_merged: 'Identity merged',
  identity_split: 'Identity split',
  consent_state_changed: 'Consent changed',
  unknown: 'Unknown',
};

interface Props {
  transitionType: string | null;
}

export const JourneyTransitionBadge: FC<Props> = ({ transitionType }) => {
  if (!transitionType || transitionType === 'same_session') return null;
  const label = TRANSITION_LABELS[transitionType] ?? transitionType;
  return (
    <div
      role="separator"
      aria-label={`Transition: ${label}`}
      className="flex items-center gap-2 py-1 pl-8"
    >
      <div className="h-px flex-1 bg-border" aria-hidden="true" />
      <span className="text-[10px] font-medium text-text-muted px-2 py-0.5 rounded-full border border-border bg-surface-secondary whitespace-nowrap">
        {label}
      </span>
      <div className="h-px flex-1 bg-border" aria-hidden="true" />
    </div>
  );
};
