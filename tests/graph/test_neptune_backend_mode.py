"""Tests for Neptune backend mode selection and fail-closed behavior."""

from __future__ import annotations

import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    for prefix in ("shared",):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    if "jwt" not in sys.modules:
        sys.modules["jwt"] = types.SimpleNamespace(
            encode=lambda *a, **kw: "stub",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception, ExpiredSignatureError=Exception, InvalidTokenError=Exception
            ),
        )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


def test_local_env_uses_in_memory_backend() -> None:
    """AETHER_ENV=local must connect using the in-memory backend."""
    import asyncio
    with backend_path():
        from shared.graph.graph import GraphClient
        os.environ["AETHER_ENV"] = "local"
        os.environ.pop("NEPTUNE_ENDPOINT", None)

        async def run():
            client = GraphClient()
            await client.connect()
            assert client.mode == "in-memory", f"Expected in-memory, got {client.mode!r}"

        asyncio.get_event_loop().run_until_complete(run())


def test_non_local_without_neptune_raises_runtime_error() -> None:
    """Non-local env without NEPTUNE_ENDPOINT must raise RuntimeError (fail-closed)."""
    import asyncio
    with backend_path():
        from shared.graph.graph import GraphClient
        os.environ["AETHER_ENV"] = "production"
        os.environ.pop("NEPTUNE_ENDPOINT", None)

        async def run():
            client = GraphClient()
            try:
                await client.connect()
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                assert "NEPTUNE_ENDPOINT" in str(e)

        try:
            asyncio.get_event_loop().run_until_complete(run())
        finally:
            os.environ["AETHER_ENV"] = "local"


def test_graph_client_mode_is_in_memory_after_local_connect() -> None:
    """GraphClient.mode must be 'in-memory' after connecting in local mode."""
    import asyncio
    with backend_path():
        from shared.graph.graph import GraphClient
        os.environ["AETHER_ENV"] = "local"
        os.environ.pop("NEPTUNE_ENDPOINT", None)

        async def run():
            client = GraphClient()
            await client.connect()
            return client.mode

        mode = asyncio.get_event_loop().run_until_complete(run())
        assert mode == "in-memory"


def test_graph_health_check_returns_true_for_in_memory() -> None:
    """GraphClient.health_check() must return True for in-memory backend."""
    import asyncio
    with backend_path():
        from shared.graph.graph import GraphClient
        os.environ["AETHER_ENV"] = "local"
        os.environ.pop("NEPTUNE_ENDPOINT", None)

        async def run():
            client = GraphClient()
            await client.connect()
            return await client.health_check()

        healthy = asyncio.get_event_loop().run_until_complete(run())
        assert healthy is True


def test_graph_client_mode_property_exists() -> None:
    with backend_path():
        from shared.graph.graph import GraphClient
        client = GraphClient()
        assert hasattr(client, "mode")
        assert client.mode == "uninitialized"
