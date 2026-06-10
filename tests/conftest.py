from __future__ import annotations

import sys
import types

try:
    import pytest_asyncio as _  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "pytest-asyncio is required for async tests. "
        "Install dev dependencies: pip install -e '.[dev]'"
    ) from exc


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
