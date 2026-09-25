"""Pytest setup for Profile 360 tests.

The shared `shared/auth/auth.py` module imports PyJWT which transitively
imports the cryptography native binding. In some sandboxed CI environments
that binding panics on import (unrelated to anything Profile 360 touches),
preventing test collection. We stub it here so test collection succeeds in
those environments. Production imports are unaffected.
"""

from __future__ import annotations

import importlib.util
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


def _is_installed(module: str) -> bool:
    """Whether ``module`` is a real, importable distribution (without importing it)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _stub_jwt_and_crypto() -> None:
    """Install lightweight stubs for jwt + cryptography ONLY when absent.

    In sandboxes without the packages (where PyJWT/cryptography cannot be
    imported) the stubs let collection proceed. When the real packages are
    installed they must never be shadowed: this conftest runs at collection
    time and ``sys.modules`` is process-global, so a stub installed merely
    because nothing had imported ``cryptography`` yet broke every later suite
    that needs the real package (``cryptography.exceptions``) in a
    whole-tree run.
    """
    if not _is_installed("jwt"):
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

    if "cryptography" not in sys.modules and not _is_installed("cryptography"):
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
