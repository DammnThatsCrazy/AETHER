"""Pytest configuration for agentic_x402 tests.

Stubs external dependencies (fastapi, asyncpg, etc.) that are not installed
in the test sandbox environment so that repository/service imports succeed.
"""

from __future__ import annotations

import os
import sys
import types


def _stub_missing_deps() -> None:
    """Install lightweight stubs for packages missing in this environment."""
    # fastapi stub
    if "fastapi" not in sys.modules:
        fake_fastapi = types.ModuleType("fastapi")
        fake_fastapi.APIRouter = object
        fake_fastapi.Request = object
        fake_fastapi.Depends = lambda x: x
        fake_fastapi.Query = lambda *a, **kw: None
        fake_fastapi.Header = lambda *a, **kw: None
        fake_fastapi.HTTPException = Exception

        class _HTTPException(Exception):
            def __init__(self, status_code=400, detail=""):
                self.status_code = status_code
                self.detail = detail

        fake_fastapi.HTTPException = _HTTPException
        sys.modules["fastapi"] = fake_fastapi
        sys.modules["fastapi.responses"] = types.SimpleNamespace(JSONResponse=dict)
        sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
        sys.modules["fastapi.middleware.cors"] = types.SimpleNamespace(CORSMiddleware=object)

    # pydantic stub
    if "pydantic" not in sys.modules:
        fake_pydantic = types.ModuleType("pydantic")
        fake_pydantic.BaseModel = object
        fake_pydantic.Field = lambda *a, **kw: None
        sys.modules["pydantic"] = fake_pydantic

    # starlette stub — each submodule is a separate SimpleNamespace so that
    # `from starlette.applications import Starlette` resolves correctly.
    if "starlette" not in sys.modules:
        _star = types.ModuleType("starlette")
        sys.modules["starlette"] = _star

    for _submod, _attrs in [
        ("starlette.applications", {"Starlette": object}),
        ("starlette.middleware", {"Middleware": object}),
        ("starlette.middleware.base", {"BaseHTTPMiddleware": object}),
        ("starlette.middleware.cors", {"CORSMiddleware": object}),
        ("starlette.requests", {"Request": object}),
        ("starlette.responses", {"Response": object, "JSONResponse": dict}),
        ("starlette.routing", {"Route": object, "Router": object}),
        ("starlette.types", {"ASGIApp": object, "Receive": object, "Scope": object, "Send": object}),
        ("starlette.datastructures", {"Headers": object, "URL": object}),
        ("starlette.concurrency", {}),
        ("starlette.background", {"BackgroundTask": object}),
        ("starlette.websockets", {"WebSocket": object}),
        ("starlette.testclient", {"TestClient": object}),
        ("starlette.staticfiles", {"StaticFiles": object}),
        ("starlette.exceptions", {"HTTPException": Exception}),
        ("starlette.status", {}),
    ]:
        if _submod not in sys.modules:
            _m = types.ModuleType(_submod)
            for _k, _v in _attrs.items():
                setattr(_m, _k, _v)
            sys.modules[_submod] = _m

    # asyncpg stub
    if "asyncpg" not in sys.modules:
        fake_asyncpg = types.ModuleType("asyncpg")
        sys.modules["asyncpg"] = fake_asyncpg

    # jwt stub
    sys.modules.setdefault(
        "jwt",
        types.SimpleNamespace(
            encode=lambda *a, **kw: "",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception,
                ExpiredSignatureError=Exception,
                InvalidTokenError=Exception,
            ),
        ),
    )

    # cryptography stub
    if "cryptography" not in sys.modules:
        fake = types.ModuleType("cryptography")

        class _Fern:
            def __init__(self, *a, **kw):
                pass
            def encrypt(self, b):
                return b
            def decrypt(self, b):
                return b

        fake.fernet = types.SimpleNamespace(Fernet=_Fern, InvalidToken=Exception)
        sys.modules["cryptography"] = fake
        sys.modules["cryptography.fernet"] = fake.fernet


_stub_missing_deps()

os.environ.setdefault("AETHER_ENV", "local")

# Make backend packages importable
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, "..", ".."))
for path in (BACKEND_ROOT, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
