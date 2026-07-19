"""Path + isolation fixtures for semantic durable-pipeline integration tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")


@pytest.fixture(autouse=True)
def durable_semantic_store():
    """Run each test against the durable store over the in-memory fallback."""
    from repositories.repos import reset_in_memory_stores
    from services.semantic_intelligence.engine import get_store, set_store
    from services.semantic_intelligence.store import DurableSemanticSentimentStore

    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    yield
    set_store(original)
    reset_in_memory_stores()
