"""Ad connectors never seed provider records or report local mock health."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from services.measurement.connectors.google_ads import GoogleAdsConnector
from services.measurement.connectors.linkedin_ads import LinkedInAdsConnector
from services.measurement.connectors.meta_ads import MetaAdsConnector
from services.measurement.connectors.microsoft_ads import MicrosoftAdsConnector
from services.measurement.connectors.reddit_ads import RedditAdsConnector
from services.measurement.connectors.tiktok_ads import TikTokAdsConnector
from services.measurement.connectors.x_ads import XAdsConnector

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connector_type", "uses_datetime"),
    [
        (GoogleAdsConnector, True),
        (MetaAdsConnector, True),
        (TikTokAdsConnector, True),
        (XAdsConnector, False),
        (RedditAdsConnector, False),
        (LinkedInAdsConnector, False),
        (MicrosoftAdsConnector, False),
    ],
)
async def test_missing_credentials_are_unavailable_not_seeded(
    connector_type, uses_datetime, monkeypatch
):
    monkeypatch.setenv("AETHER_ENV", "local")
    connector = connector_type("connector-1", "tenant-1", {}, {})
    start = (
        datetime(2026, 1, 1, tzinfo=timezone.utc)
        if uses_datetime
        else date(2026, 1, 1)
    )
    end = (
        datetime(2026, 1, 2, tzinfo=timezone.utc)
        if uses_datetime
        else date(2026, 1, 2)
    )

    result = await connector.backfill(start, end)
    health = await connector.health_check()

    assert result.spend_records_written == 0
    assert result.errors
    assert health.healthy is False


@pytest.mark.parametrize(
    "module_source",
    [
        GoogleAdsConnector,
        MetaAdsConnector,
        TikTokAdsConnector,
        XAdsConnector,
        RedditAdsConnector,
        LinkedInAdsConnector,
        MicrosoftAdsConnector,
    ],
)
def test_connector_source_has_no_runtime_seed_factory(module_source):
    import inspect

    source = inspect.getsource(module_source)
    assert "_mock_backfill" not in source
    assert "mock mode" not in source
    assert "Mock Campaign" not in source
