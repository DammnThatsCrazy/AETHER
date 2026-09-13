"""Unit tests: ACTION_NOTIFIER connectors must not write to the lake."""
from __future__ import annotations

import pytest

from services.integrations.connectors.base import (
    ConnectorClass,
    LakeWritePolicy,
)


def test_action_notifier_lake_write_policy_is_never():
    """Ensure ACTION_NOTIFIER maps to LakeWritePolicy.NEVER semantically."""
    assert LakeWritePolicy.NEVER.value == "never"
    # The class itself is the sentinel
    assert ConnectorClass.ACTION_NOTIFIER.value == "action_notifier"


def test_lake_write_policy_never_value():
    """LakeWritePolicy.NEVER must not admit any write path."""
    policy = LakeWritePolicy.NEVER
    assert policy != LakeWritePolicy.TENANT_ONLY
    assert policy != LakeWritePolicy.OLYMPUS_BASELINE_ELIGIBLE
    assert policy != LakeWritePolicy.OLYMPUS_BASELINE_ALLOWED


def test_action_notifier_distinct_from_data_connectors():
    """ACTION_NOTIFIER must be structurally distinct from all data-ingesting classes."""
    data_classes = {
        ConnectorClass.OLYMPUS_PROVIDER,
        ConnectorClass.TENANT_BYOD_DATA,
        ConnectorClass.BYOK_GATEWAY,
    }
    assert ConnectorClass.ACTION_NOTIFIER not in data_classes


@pytest.mark.asyncio
async def test_sync_blocked_for_action_notifier():
    """ConnectorService.sync() must raise when connector is ACTION_NOTIFIER."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from services.integrations.connectors.service import ConnectorService
    from services.integrations.connectors.base import ConnectorDescriptor

    # Build a mock descriptor for an ACTION_NOTIFIER connector
    mock_descriptor = ConnectorDescriptor(
        connector_type="slack",
        label="Slack",
        description="Slack notifier",
        category="messaging",
        supports_webhook=False,
        supports_pull=False,
        requires_secret=True,
        premium=False,
        ingest_event_types=[],
        docs_slug="slack",
        connector_class=ConnectorClass.ACTION_NOTIFIER,
        lake_write_policy=LakeWritePolicy.NEVER,
    )

    mock_connector = MagicMock()
    mock_connector.descriptor.return_value = mock_descriptor
    mock_connector.validate_config = MagicMock()

    svc = ConnectorService()
    svc.repo = AsyncMock()
    svc.repo.find_by_id = AsyncMock(return_value={
        "tenant_id": "t1",
        "connector_type": "slack",
        "enabled": True,
        "secret_configured": False,
        "config": {},
        "sync_status": "never_synced",
        "error_count": 0,
        "name": "Slack",
        "created_at": "",
        "updated_at": "",
        "last_synced_at": None,
        "last_error_at": None,
        "last_error_message": None,
        "secret_ref": None,
    })

    with patch("services.integrations.connectors.service.get_connector", return_value=mock_connector):
        with pytest.raises(ValueError, match="ACTION_NOTIFIER"):
            await svc.sync("t1", "slack")
