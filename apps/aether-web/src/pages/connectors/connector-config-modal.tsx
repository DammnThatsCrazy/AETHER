// Compatibility re-export — the connector config modal moved into the Settings
// shell (pages/settings/integrations/) in the End-User Lifecycle WS-1 rehome.
// Onboarding and the operational-postconditions suite import this path directly.
export {
  ConnectorConfigModal,
  connectorSavePostcondition,
  connectorTestPostcondition,
} from '../settings/integrations/connector-config-modal';
