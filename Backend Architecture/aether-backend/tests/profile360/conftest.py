"""Pytest setup for Profile 360 tests.

The shared `shared/auth/auth.py` module imports PyJWT which transitively
imports the cryptography native binding. In some sandboxed CI environments
that binding panics on import (unrelated to anything Profile 360 touches),
preventing test collection. We stub it here so test collection succeeds in
those environments. Production imports are unaffected.
"""

from __future__ import annotations

import os
import sys
import types

# Python 3.14 no longer auto-creates a main-thread event loop for
# asyncio.get_event_loop(). Several legacy Profile360 smoke tests still use
# that pattern, so keep the tests version-portable until they are migrated to
# pytest-asyncio/asyncio.run.
import asyncio


class _CompatEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def get_event_loop(self):  # type: ignore[override]
        try:
            return super().get_event_loop()
        except RuntimeError:
            loop = self.new_event_loop()
            self.set_event_loop(loop)
            return loop


asyncio.set_event_loop_policy(_CompatEventLoopPolicy())


def _stub_jwt_and_crypto() -> None:
    """Forcibly install lightweight stubs for jwt + cryptography.

    PyJWT/cryptography unconditionally panic on import in this sandbox
    (Rust pyo3 binding failure), and that panic is *not* a Python exception
    we can catch. So we install stubs into sys.modules **before any code
    paths that might import them** run. Production runs always have the
    real packages and never reach this code.
    """
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

    if "cryptography" not in sys.modules:
        fake = types.ModuleType("cryptography")

        class _Fern:
            def __init__(self, *args, **kwargs):
                pass

            def encrypt(self, b):
                return b

            def decrypt(self, b):
                return b

        fake.fernet = types.SimpleNamespace(Fernet=_Fern, InvalidToken=Exception)
        sys.modules["cryptography"] = fake
        sys.modules["cryptography.fernet"] = fake.fernet


_stub_jwt_and_crypto()

os.environ.setdefault("AETHER_ENV", "local")

# Make repository paths importable from the test files themselves.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for path in (ROOT, os.path.dirname(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
