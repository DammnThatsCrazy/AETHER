from __future__ import annotations

import asyncio
import inspect
import sys
import types

try:
    import pytest_asyncio as _pytest_asyncio  # noqa: F401
except ImportError:  # pragma: no cover - exercised only in constrained sandboxes
    _pytest_asyncio = None


def pytest_addoption(parser):
    """Accept pytest-xdist's -n option when xdist cannot be installed locally.

    CI installs pytest-xdist from pyproject.toml. In network-restricted agent
    sandboxes, this keeps the same test set runnable serially instead of failing
    during argument parsing.
    """
    try:
        import xdist  # noqa: F401
        return
    except ImportError:
        pass
    parser._anonymous._addoption("-n", "--numprocesses", action="store", default=None, help="xdist compatibility shim; runs serially when pytest-xdist is unavailable")


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run async test functions with an event loop")


def pytest_pyfunc_call(pyfuncitem):
    """Small pytest-asyncio-compatible fallback for sandboxed environments.

    The project still declares pytest-asyncio in pyproject.toml and CI installs it.
    This hook preserves test coverage when package installation is unavailable by
    executing coroutine test functions instead of skipping them.
    """
    if _pytest_asyncio is not None or not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    testargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(pyfuncitem.obj(**testargs))
    return True


def _has_working_cffi() -> bool:
    """Return True only when the cffi C-extension is importable.

    PyJWT → cryptography → _cffi_backend: if the native binding is missing
    the pyo3 Rust layer panics *before* Python can catch an ImportError.
    We probe the C-extension first; if it is absent we install lightweight
    stubs so test collection can still proceed in sandbox / CI environments.
    Production always has cffi installed and never reaches the stub path.
    """
    try:
        import _cffi_backend  # noqa: F401
        return True
    except (ImportError, Exception):
        return False


if _has_working_cffi():
    # Import the real PyJWT before any test module runs. Several modules stub
    # `jwt` in sys.modules at import time, guarded by
    # `if "jwt" not in sys.modules`. Loading the real module here makes those
    # guards skip jwt — preventing a MagicMock/stub from leaking onto a
    # pytest-xdist worker and breaking the real JWT auth tests with
    # "module 'jwt' has no attribute 'encode'".
    import jwt as _real_jwt  # noqa: E402,F401
else:
    # cffi C-extension unavailable: pre-install stubs so nothing downstream
    # can trigger the pyo3 panic.  The stubs expose the minimum surface needed
    # by auth middleware and SDK tests.
    sys.modules.setdefault(
        "jwt",
        types.SimpleNamespace(
            encode=lambda *a, **kw: "stub-token",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception,
                ExpiredSignatureError=Exception,
                InvalidTokenError=Exception,
            ),
        ),
    )
    if "cryptography" not in sys.modules:
        _crypto = types.ModuleType("cryptography")

        class _StubFernet:
            def __init__(self, *a, **kw):
                pass

            def encrypt(self, data: bytes) -> bytes:
                return data

            def decrypt(self, data: bytes) -> bytes:
                return data

        _crypto.fernet = types.SimpleNamespace(  # type: ignore[attr-defined]
            Fernet=_StubFernet,
            InvalidToken=Exception,
        )
        sys.modules["cryptography"] = _crypto
        sys.modules["cryptography.fernet"] = _crypto.fernet  # type: ignore[attr-defined]
