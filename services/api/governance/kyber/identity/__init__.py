"""Kyber workforce identity — who an Olympus operator is, and for how long.

Workforce identity is not tenant identity. Nothing in this package can be
reached by an Aether customer, and no Aether authentication path can create a
record here. A workforce principal exists only because someone holding
``kyber.workforce.manage`` invited it, or because the one-time founder
bootstrap created the very first one.

Module map:

``principals``      persistence and authority resolution (the fail-closed core)
``invitations``     single-use, email-bound, founder-limited admission
``oidc``            backend-side Google authorization-code + PKCE
``bootstrap``       the one-time founder bootstrap, and its permanent marker
``directory_sync``  reconciliation with Google Workspace, and its honest limits
``lifecycle``       the single offboarding funnel across identity/sessions/devices
``routes``          the HTTP surface

``routes`` is intentionally not imported here: it pulls in FastAPI and the
access dependency, and every service in this package must stay importable by
the access plane without that cycle.
"""
from .bootstrap import FounderBootstrapService, founder_bootstrap_service
from .directory_sync import (
    DirectorySyncResult,
    DirectorySyncService,
    build_directory_sync_coro,
    directory_sync_service,
)
from .invitations import InvitationService, invitation_service
from .lifecycle import offboard_principal, revoke_operator_access
from .oidc import (
    GoogleOidcClient,
    MockOidcProvider,
    OidcConfig,
    OidcError,
    OidcIdentity,
    OidcTransaction,
    OidcTransactionStore,
    get_oidc_client,
    oidc_transaction_store,
)
from .principals import (
    CapabilityGrantRepository,
    PrincipalService,
    RoleBindingRepository,
    WorkforcePrincipalRepository,
    principal_service,
    record_authentication_event,
)

__all__ = [
    "CapabilityGrantRepository",
    "DirectorySyncResult",
    "DirectorySyncService",
    "FounderBootstrapService",
    "GoogleOidcClient",
    "InvitationService",
    "MockOidcProvider",
    "OidcConfig",
    "OidcError",
    "OidcIdentity",
    "OidcTransaction",
    "OidcTransactionStore",
    "PrincipalService",
    "RoleBindingRepository",
    "WorkforcePrincipalRepository",
    "build_directory_sync_coro",
    "directory_sync_service",
    "founder_bootstrap_service",
    "get_oidc_client",
    "invitation_service",
    "offboard_principal",
    "oidc_transaction_store",
    "principal_service",
    "record_authentication_event",
    "revoke_operator_access",
]
