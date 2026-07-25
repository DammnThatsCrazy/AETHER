export { SecurityPage } from './security-page';

// Kyber operator security console. Intended routes:
//   /security/workforce   -> WorkforcePage
//   /security/invitations -> InvitationsPage
//   /security/roles       -> RolesPage
//   /security/devices     -> DevicesPage
//   /security/sessions    -> SessionsPage
//   /security/access      -> AccessPage
//   /security/audit       -> AuditPage
export { WorkforcePage } from './workforce-page';
export { InvitationsPage } from './invitations-page';
export { RolesPage } from './roles-page';
export { DevicesPage } from './devices-page';
export { SessionsPage } from './sessions-page';
export { AccessPage } from './access-page';
export { AuditPage } from './audit-page';

export { SecurityPageShell, AsyncSection, SecurityCard, AdvisoryNote } from './security-shell';
export { useSecurityResource } from './use-security-resource';
