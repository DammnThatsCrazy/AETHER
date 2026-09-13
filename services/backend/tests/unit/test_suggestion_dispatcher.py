"""Unit tests for the Suggestion dispatcher."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.suggestions.dispatcher import (
    _IDEMPOTENT_STATUSES,
    _resolve_dispatch_mode,
    dispatch,
)
from services.suggestions.models import (
    SuggestionSource,
    SuggestionStatus,
)
from shared.common.common import BadRequestError


def _run(coro):
    return asyncio.run(coro)


def _make_tenant(tenant_id: str = "tenant_abc") -> MagicMock:
    tenant = MagicMock()
    tenant.tenant_id = tenant_id
    return tenant


def _make_suggestion(
    suggestion_id: str = None,
    tenant_id: str = "tenant_abc",
    status: str = SuggestionStatus.APPROVED.value,
    source: str = SuggestionSource.RULE.value,
    execution_eligible: bool = False,
    delivery_eligible: bool = True,
) -> dict:
    return {
        "id": suggestion_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "status": status,
        "source": source,
        "execution_eligible": execution_eligible,
        "delivery_eligible": delivery_eligible,
        "audit_trail": [],
        "title": "Test",
        "summary": "Summary",
    }


def _make_service(deliver_result: dict = None) -> MagicMock:
    svc = MagicMock()
    svc._repo = MagicMock()
    svc._producer = MagicMock()
    svc.deliver_suggestion = AsyncMock(return_value=deliver_result or {})
    return svc


# ---------------------------------------------------------------------------
# _resolve_dispatch_mode()
# ---------------------------------------------------------------------------

def test_resolve_mode_recommendation_eligible_returns_legacy_execute():
    suggestion = _make_suggestion(
        source=SuggestionSource.RECOMMENDATION_ENGINE.value,
        execution_eligible=True,
    )
    mode = _resolve_dispatch_mode(suggestion)
    assert mode == "legacy_recommendation_execute"


def test_resolve_mode_notification_source_delivery_eligible_returns_notify_only():
    suggestion = _make_suggestion(
        source=SuggestionSource.NOTIFICATION_INTELLIGENCE.value,
        delivery_eligible=True,
    )
    mode = _resolve_dispatch_mode(suggestion)
    assert mode == "notify_only"


def test_resolve_mode_data_quality_source_delivery_eligible_returns_notify_only():
    suggestion = _make_suggestion(
        source=SuggestionSource.DATA_QUALITY.value,
        delivery_eligible=True,
    )
    mode = _resolve_dispatch_mode(suggestion)
    assert mode == "notify_only"


def test_resolve_mode_governance_source_delivery_eligible_returns_notify_only():
    suggestion = _make_suggestion(
        source=SuggestionSource.GOVERNANCE.value,
        delivery_eligible=True,
    )
    mode = _resolve_dispatch_mode(suggestion)
    assert mode == "notify_only"


def test_resolve_mode_operator_source_returns_no_op():
    suggestion = _make_suggestion(
        source=SuggestionSource.OPERATOR.value,
        execution_eligible=False,
        delivery_eligible=False,
    )
    mode = _resolve_dispatch_mode(suggestion)
    assert mode == "no_op"


def test_resolve_mode_recommendation_not_eligible_returns_no_op():
    suggestion = _make_suggestion(
        source=SuggestionSource.RECOMMENDATION_ENGINE.value,
        execution_eligible=False,
        delivery_eligible=False,
    )
    mode = _resolve_dispatch_mode(suggestion)
    assert mode == "no_op"


# ---------------------------------------------------------------------------
# dispatch() — guard: unapproved suggestion raises
# ---------------------------------------------------------------------------

def test_dispatch_raises_for_non_approved_status():
    suggestion = _make_suggestion(status=SuggestionStatus.SUGGESTED.value)
    tenant = _make_tenant()
    svc = _make_service()

    with pytest.raises(BadRequestError, match="APPROVED"):
        _run(dispatch(suggestion, tenant, svc))


def test_dispatch_raises_for_detected_status():
    suggestion = _make_suggestion(status=SuggestionStatus.DETECTED.value)
    tenant = _make_tenant()
    svc = _make_service()

    with pytest.raises(BadRequestError):
        _run(dispatch(suggestion, tenant, svc))


def test_dispatch_raises_for_review_required_status():
    suggestion = _make_suggestion(status=SuggestionStatus.REVIEW_REQUIRED.value)
    tenant = _make_tenant()
    svc = _make_service()

    with pytest.raises(BadRequestError):
        _run(dispatch(suggestion, tenant, svc))


# ---------------------------------------------------------------------------
# dispatch() — notify_only path
# ---------------------------------------------------------------------------

def test_dispatch_notify_only_calls_notification_adapter():
    delivered = {
        **_make_suggestion(
            source=SuggestionSource.NOTIFICATION_INTELLIGENCE.value,
            delivery_eligible=True,
        ),
        "status": SuggestionStatus.DELIVERED.value,
    }
    suggestion = _make_suggestion(
        source=SuggestionSource.NOTIFICATION_INTELLIGENCE.value,
        delivery_eligible=True,
    )
    tenant = _make_tenant()
    svc = _make_service(deliver_result=delivered)

    # dispatcher imports deliver_suggestion_via_notification lazily from the
    # notification adapter module at call time, so that's the real seam to patch.
    with patch(
        "services.suggestions.adapters.notification_adapter.deliver_suggestion_via_notification",
        AsyncMock(return_value=delivered),
    ) as mock_deliver:
        result = _run(dispatch(suggestion, tenant, svc))

    mock_deliver.assert_called_once()


def test_dispatch_notify_only_returns_delivered_record():
    delivered = {
        **_make_suggestion(
            source=SuggestionSource.NOTIFICATION_INTELLIGENCE.value,
            delivery_eligible=True,
        ),
        "status": SuggestionStatus.DELIVERED.value,
    }
    suggestion = _make_suggestion(
        source=SuggestionSource.NOTIFICATION_INTELLIGENCE.value,
        delivery_eligible=True,
    )
    tenant = _make_tenant()
    svc = _make_service()

    with patch(
        "services.suggestions.adapters.notification_adapter.deliver_suggestion_via_notification",
        AsyncMock(return_value=delivered),
    ):
        result = _run(dispatch(suggestion, tenant, svc))
    assert result["status"] == SuggestionStatus.DELIVERED.value


# ---------------------------------------------------------------------------
# dispatch() — idempotency
# ---------------------------------------------------------------------------

def test_dispatch_idempotent_returns_current_state_when_already_executed():
    suggestion = _make_suggestion(status=SuggestionStatus.EXECUTED.value)
    tenant = _make_tenant()
    svc = _make_service()

    result = _run(dispatch(suggestion, tenant, svc))
    # Should return immediately with no execution
    assert result == suggestion
    svc.deliver_suggestion.assert_not_called()


def test_dispatch_idempotent_returns_current_state_when_already_delivered():
    suggestion = _make_suggestion(status=SuggestionStatus.DELIVERED.value)
    tenant = _make_tenant()
    svc = _make_service()

    result = _run(dispatch(suggestion, tenant, svc))
    assert result == suggestion
    svc.deliver_suggestion.assert_not_called()


def test_dispatch_idempotent_returns_current_state_when_already_closed():
    suggestion = _make_suggestion(status=SuggestionStatus.CLOSED.value)
    tenant = _make_tenant()
    svc = _make_service()

    result = _run(dispatch(suggestion, tenant, svc))
    assert result == suggestion


def test_idempotent_statuses_contains_executed_delivered_closed():
    assert SuggestionStatus.EXECUTED.value in _IDEMPOTENT_STATUSES
    assert SuggestionStatus.DELIVERED.value in _IDEMPOTENT_STATUSES
    assert SuggestionStatus.CLOSED.value in _IDEMPOTENT_STATUSES


# ---------------------------------------------------------------------------
# dispatch() — no_op path
# ---------------------------------------------------------------------------

def test_dispatch_no_op_calls_deliver_suggestion():
    delivered = {
        **_make_suggestion(source=SuggestionSource.OPERATOR.value),
        "status": SuggestionStatus.DELIVERED.value,
    }
    suggestion = _make_suggestion(
        source=SuggestionSource.OPERATOR.value,
        execution_eligible=False,
        delivery_eligible=False,
    )
    tenant = _make_tenant()
    svc = _make_service(deliver_result=delivered)

    result = _run(dispatch(suggestion, tenant, svc))
    svc.deliver_suggestion.assert_called_once()


# ---------------------------------------------------------------------------
# dispatch() — execution_enabled gate
# ---------------------------------------------------------------------------

def test_dispatch_legacy_execute_raises_when_execution_disabled():
    suggestion = _make_suggestion(
        source=SuggestionSource.RECOMMENDATION_ENGINE.value,
        execution_eligible=True,
    )
    tenant = _make_tenant()
    svc = _make_service()

    with pytest.raises(BadRequestError, match="disabled"):
        _run(dispatch(suggestion, tenant, svc, execution_enabled=False))
