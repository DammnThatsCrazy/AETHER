"""Pytest configuration for agentic_x402 tests.

Historically this module stubbed external dependencies (fastapi, pydantic,
starlette, asyncpg, jwt, cryptography) so repository/service imports would
succeed in a sandbox where those packages were not installed.

Why the stubbing is now conditional
-----------------------------------
Two defects combined to corrupt every suite collected after this package.

First, the starlette submodule loop sat *outside* the ``if "starlette" not in
sys.modules`` guard, so it executed unconditionally — including when starlette
was genuinely installed.

Second, each stub was gated on ``"<name>" not in sys.modules`` — "has this been
imported yet?" — which is not the same question as "is the real package
installed?". ``starlette.testclient`` is not imported until something asks for
it, so the loop registered a fake exposing ``TestClient = object`` on top of a
perfectly good starlette.

Conftest bodies execute at collection time and ``sys.modules`` is process-global,
so that fake outlived this package. Any test collected afterwards that did
``TestClient(app)`` resolved to ``object`` and raised ``TypeError: object() takes
no arguments``. It reproduced only in a whole-tree run — each affected file
passed in isolation — which is precisely why it stayed hidden while no gate
executed the backend tree. ``jwt`` and ``cryptography`` carried the same defect
via ``setdefault`` and an unguarded presence check.

The stubs are therefore installed only when the real distribution is genuinely
absent, and a stub is never layered over a package that is really installed.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types


def _is_installed(module: str) -> bool:
    """Report whether ``module`` is a real, importable distribution.

    ``find_spec`` is used rather than ``module in sys.modules`` so the answer
    does not depend on import order, and rather than ``import`` so that merely
    asking the question does not pull heavy packages into every test session.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _stub_missing_deps() -> None:
    """Install lightweight stubs only for packages missing from this environment."""
    if not _is_installed("fastapi"):
        fake_fastapi = types.ModuleType("fastapi")
        fake_fastapi.APIRouter = object
        fake_fastapi.Request = object
        fake_fastapi.Depends = lambda x: x
        fake_fastapi.Query = lambda *a, **kw: None
        fake_fastapi.Header = lambda *a, **kw: None

        class _HTTPException(Exception):
            def __init__(self, status_code=400, detail=""):
                self.status_code = status_code
                self.detail = detail

        fake_fastapi.HTTPException = _HTTPException
        sys.modules["fastapi"] = fake_fastapi
        sys.modules["fastapi.responses"] = types.SimpleNamespace(JSONResponse=dict)
        sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
        sys.modules["fastapi.middleware.cors"] = types.SimpleNamespace(CORSMiddleware=object)

    if not _is_installed("pydantic"):
        fake_pydantic = types.ModuleType("pydantic")
        fake_pydantic.BaseModel = object
        fake_pydantic.Field = lambda *a, **kw: None
        # ConfigDict is used at class-definition time by shared graph mutation
        # models (imported transitively via the canonical mutation gateway);
        # the stub must expose it or those modules fail to import.
        fake_pydantic.ConfigDict = lambda *a, **kw: dict(*a, **kw)
        sys.modules["pydantic"] = fake_pydantic

    # starlette stub — each submodule is a separate module object so that
    # `from starlette.applications import Starlette` resolves correctly. The
    # entire block, submodule loop included, is skipped when starlette is really
    # installed; layering a fake submodule over a real package is what corrupted
    # TestClient for every suite collected after this one.
    if not _is_installed("starlette"):
        sys.modules.setdefault("starlette", types.ModuleType("starlette"))
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

    if not _is_installed("asyncpg"):
        sys.modules["asyncpg"] = types.ModuleType("asyncpg")

    if not _is_installed("jwt"):
        sys.modules["jwt"] = types.SimpleNamespace(
            encode=lambda *a, **kw: "",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception,
                ExpiredSignatureError=Exception,
                InvalidTokenError=Exception,
            ),
        )

    if not _is_installed("cryptography"):
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
