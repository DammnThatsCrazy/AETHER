"""Shared fixtures for card-linked payment rail tests."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

BACKEND = str(Path(__file__).parents[3] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


@pytest.fixture(autouse=True)
def _fresh_repositories():
    from services.card_linked_payments.repositories import reset_card_linked_repositories

    reset_card_linked_repositories()
    yield
    reset_card_linked_repositories()


@pytest.fixture()
def tenant() -> str:
    return f"tenant-cl-{uuid4().hex[:8]}"


@pytest.fixture()
def ingestion():
    from config.settings import settings
    from services.card_linked_payments.ingestion import CardLinkedIngestionService

    return CardLinkedIngestionService(settings)
