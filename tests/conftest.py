from __future__ import annotations

try:
    import pytest_asyncio as _  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "pytest-asyncio is required for async tests. "
        "Install dev dependencies: pip install -e '.[dev]'"
    ) from exc
