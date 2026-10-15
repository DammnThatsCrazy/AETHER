"""OAuth authorization broker for the Integration Control Plane.

An additive, route-free library that drives the server-side OAuth
authorization-code flow: PKCE (:mod:`.pkce`), signed capability-bound state
(:mod:`.state`), static provider config (:mod:`.provider_config`), and the
:class:`~.broker.AuthorizationBroker` that exchanges codes and lands tokens in
the credential platform as :class:`OAuthTokenCredential`\\ s.
"""

from __future__ import annotations

from .broker import (
    AuthorizationBroker,
    AuthorizationChallenge,
    AuthorizationResult,
    FlowStore,
    HttpPost,
    InMemoryFlowStore,
    OAuthBrokerError,
)
from .pkce import (
    CHALLENGE_METHOD,
    MAX_VERIFIER_LENGTH,
    MIN_VERIFIER_LENGTH,
    PkcePair,
    compute_challenge,
    generate_pkce,
    verify_pkce,
)
from .provider_config import OAUTH_PROVIDERS, OAuthProviderConfig
from .state import (
    DEFAULT_TTL_SECONDS,
    InMemoryNonceStore,
    OAuthState,
    OAuthStateError,
    SingleUseNonceStore,
    issue_state,
    verify_state,
)

__all__ = [
    "AuthorizationBroker",
    "AuthorizationChallenge",
    "AuthorizationResult",
    "CHALLENGE_METHOD",
    "DEFAULT_TTL_SECONDS",
    "FlowStore",
    "HttpPost",
    "InMemoryFlowStore",
    "InMemoryNonceStore",
    "MAX_VERIFIER_LENGTH",
    "MIN_VERIFIER_LENGTH",
    "OAUTH_PROVIDERS",
    "OAuthBrokerError",
    "OAuthProviderConfig",
    "OAuthState",
    "OAuthStateError",
    "PkcePair",
    "SingleUseNonceStore",
    "compute_challenge",
    "generate_pkce",
    "issue_state",
    "verify_pkce",
    "verify_state",
]
