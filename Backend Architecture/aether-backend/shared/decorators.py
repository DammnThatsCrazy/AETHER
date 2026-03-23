"""
Aether Shared — @aether/decorators
Shared route decorators and utilities for DRY backend route consolidation.

Provides:
    - ``@api_response``         — auto-wrap handler return values in ``APIResponse``
    - ``require_permission()``  — FastAPI ``Depends()`` factory for permission checks
    - ``paginate_response()``   — standard offset-based pagination utility
    - ``aether_exception_handler()`` — unified ``AetherError`` -> HTTP response mapper
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Optional

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.applications import Starlette

from shared.auth.auth import APIKeyValidator, TenantContext
from shared.common.common import AetherError, APIResponse
from shared.logger.logger import get_logger

logger = get_logger("aether.shared.decorators")

# Re-usable validator accessor — initialization is deferred until first use so
# modules that do not require auth at import time are not blocked by startup config.
_api_key_validator: APIKeyValidator | None = None


def _get_api_key_validator() -> APIKeyValidator:
    global _api_key_validator
    if _api_key_validator is None:
        _api_key_validator = APIKeyValidator()
    return _api_key_validator


# ════════════════════════════════════════════════════════════════════════════
# 1.  @api_response decorator
# ════════════════════════════════════════════════════════════════════════════

def api_response(fn: Callable) -> Callable:
    """Wrap the return value of a route handler in ``APIResponse.to_dict()``.

    If the handler already returns a ``dict`` with a ``"data"`` key (i.e. it
    was already wrapped), the decorator is a no-op so existing callers are not
    broken during incremental migration.

    Any ``AetherError`` raised inside the handler is caught and converted to a
    JSON error response with the appropriate HTTP status code, keeping the
    existing error contract intact.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = await fn(*args, **kwargs)

            # Already wrapped — pass through unchanged.
            if isinstance(result, dict) and "data" in result and "meta" in result:
                return result

            # Wrap in the standard envelope.
            return APIResponse(data=result).to_dict()

        except AetherError as exc:
            # Convert domain errors to HTTP responses using the error code.
            return JSONResponse(
                status_code=exc.code.value,
                content=exc.to_dict(),
            )
        except HTTPException:
            # Let FastAPI's native exception handling deal with these.
            raise

    return wrapper


# ════════════════════════════════════════════════════════════════════════════
# 2.  require_permission() — FastAPI Depends() factory
# ════════════════════════════════════════════════════════════════════════════

def require_permission(
    scope: Optional[str] = None,
) -> Callable:
    """Return a FastAPI dependency that validates the ``X-API-Key`` header
    and (optionally) checks that the resolved tenant has *scope*.

    Usage::

        @router.get("/protected")
        async def protected(tenant: TenantContext = Depends(require_permission("read"))):
            ...

    When *scope* is ``None`` only authentication is enforced (any valid key).
    """

    async def _dependency(
        x_api_key: str = Header(..., alias="X-API-Key"),
    ) -> TenantContext:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Missing API key")

        try:
            tenant = _get_api_key_validator().validate(x_api_key)
        except AetherError as exc:
            raise HTTPException(status_code=exc.code.value, detail=exc.message)

        if scope is not None:
            try:
                tenant.require_permission(scope)
            except AetherError as exc:
                raise HTTPException(status_code=exc.code.value, detail=exc.message)

        return tenant

    return _dependency


# Convenience alias: authenticate without a specific permission scope.
require_api_key = require_permission(None)


async def require_api_key_raw(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    """Validate the ``X-API-Key`` header and return the raw key string.

    Use this dependency when the route handler needs the literal API key
    value (e.g. for store lookups keyed by API key) rather than a
    ``TenantContext`` object.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    return x_api_key


# ════════════════════════════════════════════════════════════════════════════
# 3.  paginate_response() utility
# ════════════════════════════════════════════════════════════════════════════

def paginate_response(
    items: list,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Return a standardised page slice with pagination metadata.

    Parameters
    ----------
    items:
        The full list of items (pre-filtering).
    page:
        1-based page number.
    page_size:
        Maximum items per page (clamped to 1..200).

    Returns
    -------
    dict with ``items``, ``total``, ``page``, ``page_size``, and
    ``total_pages`` keys.
    """
    page = max(page, 1)
    page_size = max(min(page_size, 200), 1)
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


# ════════════════════════════════════════════════════════════════════════════
# 4.  Exception handler registration helper
# ════════════════════════════════════════════════════════════════════════════

def register_error_handlers(app: Starlette) -> None:
    """Attach a global ``AetherError`` exception handler to a FastAPI/Starlette app.

    Call once at application startup::

        app = FastAPI()
        register_error_handlers(app)
    """

    @app.exception_handler(AetherError)
    async def _handle_aether_error(
        request: Request, exc: AetherError,
    ) -> JSONResponse:
        logger.warning(
            "AetherError %s: %s", exc.code.value, exc.message,
        )
        return JSONResponse(
            status_code=exc.code.value,
            content=exc.to_dict(),
        )
