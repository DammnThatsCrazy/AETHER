"""Kyber session plane — cookies, sessions, step-up and request validation.

Four authority layers ride one opaque handle: presence, operator authority,
step-up elevation, and (in the device plane) device registration. See
:mod:`services.kyber.sessions.service` for how the windows compose.

Nothing here decides authorization. ``access.dependencies`` composes a
validated session with capabilities, disclosure levels and tenant scopes; this
package only answers "is this handle live, and what did it prove".
"""
from .cookies import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    clear_kyber_cookies,
    clear_session_cookie,
    read_session_token,
    set_csrf_cookie,
    set_session_cookie,
)
from .service import (
    KyberSessionRepository,
    KyberSessionService,
    hash_token,
    session_service,
)
from .step_up import StepUpGrantRepository, StepUpService, step_up_service
from .validation import (
    is_safe_method,
    requires_rotation,
    validate_mutating_request,
    verify_csrf,
    verify_origin,
    verify_sec_fetch_site,
)

__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "SESSION_COOKIE_NAME",
    "KyberSessionRepository",
    "KyberSessionService",
    "StepUpGrantRepository",
    "StepUpService",
    "clear_kyber_cookies",
    "clear_session_cookie",
    "hash_token",
    "is_safe_method",
    "read_session_token",
    "requires_rotation",
    "session_service",
    "set_csrf_cookie",
    "set_session_cookie",
    "step_up_service",
    "validate_mutating_request",
    "verify_csrf",
    "verify_origin",
    "verify_sec_fetch_site",
]
