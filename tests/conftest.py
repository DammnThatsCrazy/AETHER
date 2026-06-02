from __future__ import annotations

try:
    import pytest_asyncio as _  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "pytest-asyncio is required for async tests. "
        "Install dev dependencies: pip install -e '.[dev]'"
    ) from exc

# Import the real PyJWT before any test module runs. Several modules stub `jwt`
# in sys.modules at import time, guarded by `if "jwt" not in sys.modules`
# (e.g. test_quota_flusher, test_overage_calculator, test_attribution_models,
# test_sdk_identity_resolve). conftest is imported before all test files, so
# loading the real module here makes those guards skip `jwt` — preventing a
# MagicMock/stub from leaking onto a pytest-xdist worker and breaking the real
# JWT auth tests with "module 'jwt' has no attribute 'encode'".
import jwt as _real_jwt  # noqa: E402,F401
