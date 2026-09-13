"""Connector currency-preservation regression (Section 14).

The ad connectors used to hardcode ``currency="USD"`` on every
``ExternalCampaignMetric`` regardless of the ad account's real billing
currency, silently discarding native currency / account timezone and — for
Microsoft — rounding money through ``float``.

These tests prove each connector now:
  * preserves a non-USD provider/account currency (EUR/GBP/JPY/CAD) instead of
    hardcoding USD,
  * marks records that genuinely fall back to the documented USD default,
  * preserves the source/account timezone, and
  * (Microsoft) parses the native spend string straight to ``Decimal`` without
    float rounding.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from services.measurement.connectors import (
    linkedin_ads,
    microsoft_ads,
    reddit_ads,
    tiktok_ads,
    x_ads,
)
from services.measurement.connectors.writer import ExternalCampaignMetric, WriteResult

ALL_MODULES = [microsoft_ads, linkedin_ads, x_ads, reddit_ads, tiktok_ads]


# ---------------------------------------------------------------------------
# Pure helper tests — every connector's currency/timezone resolver
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mod", ALL_MODULES, ids=lambda m: m._CONNECTOR_TYPE)
def test_provider_row_currency_preserved(mod):
    """A currency reported on the provider row wins and is normalized upper-case."""
    code, is_default = mod._resolve_billing_currency({}, row_currency="eur")
    assert code == "EUR"
    assert is_default is False


@pytest.mark.parametrize("mod", ALL_MODULES, ids=lambda m: m._CONNECTOR_TYPE)
def test_account_config_currency_preserved(mod):
    """When the row omits currency, the account-settings (config) currency is used."""
    for key in ("currency", "account_currency", "billing_currency"):
        code, is_default = mod._resolve_billing_currency({key: "GBP"})
        assert code == "GBP", key
        assert is_default is False, key


@pytest.mark.parametrize("mod", ALL_MODULES, ids=lambda m: m._CONNECTOR_TYPE)
def test_row_currency_beats_config(mod):
    """Provider row currency takes precedence over the account default."""
    code, is_default = mod._resolve_billing_currency({"currency": "USD"}, row_currency="JPY")
    assert code == "JPY"
    assert is_default is False


@pytest.mark.parametrize("mod", ALL_MODULES, ids=lambda m: m._CONNECTOR_TYPE)
def test_usd_default_is_marked_only_when_genuinely_absent(mod):
    """USD is only returned as a *flagged* fallback when no real currency exists."""
    code, is_default = mod._resolve_billing_currency({})
    assert code == "USD"
    assert is_default is True

    # Blank / whitespace values do not count as a real currency.
    code, is_default = mod._resolve_billing_currency({"currency": "   "}, row_currency="")
    assert code == "USD"
    assert is_default is True


@pytest.mark.parametrize("mod", ALL_MODULES, ids=lambda m: m._CONNECTOR_TYPE)
def test_source_timezone_preserved(mod):
    """Account/report timezone is preserved from config, defaulting to UTC."""
    assert mod._resolve_source_timezone({}) == "UTC"
    for key in ("time_zone", "timezone", "account_timezone"):
        assert mod._resolve_source_timezone({key: "Europe/Berlin"}) == "Europe/Berlin", key
    # Provider row timezone wins.
    assert mod._resolve_source_timezone({"timezone": "UTC"}, row_timezone="America/New_York") == (
        "America/New_York"
    )


# ---------------------------------------------------------------------------
# Microsoft: money must not be rounded through float
# ---------------------------------------------------------------------------


def test_microsoft_spend_not_float_rounded():
    """_parse_spend keeps native decimal precision that float() would destroy."""
    high_precision = "12345678901234567.89"
    parsed = microsoft_ads._parse_spend(high_precision)
    assert parsed == Decimal(high_precision)
    # The old float path loses precision — prove we are strictly better.
    float_rounded = Decimal(str(float(high_precision)))
    assert parsed != float_rounded


def test_microsoft_parse_spend_handles_thousands_and_empty():
    assert microsoft_ads._parse_spend("1,234.56") == Decimal("1234.56")
    assert microsoft_ads._parse_spend("") == Decimal("0")
    assert microsoft_ads._parse_spend(None) == Decimal("0")
    assert microsoft_ads._parse_spend("not-a-number") == Decimal("0")


# ---------------------------------------------------------------------------
# End-to-end: resolved currency actually reaches ExternalCampaignMetric
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json = {} if json_data is None else json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _SingleGetClient:
    """Fake httpx.AsyncClient whose single GET returns a canned response."""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        return self._resp


def _install_capture(connector) -> list[ExternalCampaignMetric]:
    """Replace the connector's writer so we can inspect the emitted metrics."""
    captured: list[ExternalCampaignMetric] = []

    async def _capture(tenant_id, connector_id, metrics_list, **kwargs):
        captured.extend(metrics_list)
        return WriteResult(spend_records_written=len(metrics_list))

    connector._writer.write_metrics = _capture
    return captured


async def test_tiktok_preserves_non_usd_currency_and_timezone(monkeypatch):
    conn = tiktok_ads.TikTokAdsConnector(
        "c-tt", "t1", {"access_token": "tok", "advertiser_id": "adv1"}, {}
    )

    async def _fake_fetch(start_date, end_date):
        return [
            {
                "campaign_id": "cmp1",
                "campaign_name": "Campaign 1",
                "stat_time_day": "2026-01-15",
                "impressions": 100,
                "clicks": 5,
                "spend": "12.34",
                "currency": "EUR",
                "timezone": "Europe/Berlin",
            }
        ]

    monkeypatch.setattr(conn, "_fetch_spend", _fake_fetch)
    captured = _install_capture(conn)

    from datetime import datetime, timezone

    await conn.backfill(
        datetime(2026, 1, 15, tzinfo=timezone.utc),
        datetime(2026, 1, 15, 23, 59, 59, tzinfo=timezone.utc),
    )

    assert len(captured) == 1
    m = captured[0]
    assert m.currency == "EUR"
    assert m.currency != "USD"
    assert m.source_timezone == "Europe/Berlin"
    assert m.spend == Decimal("12.34")
    assert m.raw_dimensions["currency_source"] == "provider"


async def test_linkedin_uses_account_currency_from_config(monkeypatch):
    # LinkedIn's adAnalytics element carries no currency code; the account
    # currency must come from account settings (connector config).
    element = {
        "dateRange": {"start": {"year": 2026, "month": 1, "day": 15}},
        "pivotValue": "urn:li:sponsoredCampaign:99",
        "costInLocalCurrency": "12.34",
        "impressions": 100,
        "clicks": 5,
    }
    resp = _Resp(json_data={"elements": [element]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _SingleGetClient(resp))

    conn = linkedin_ads.LinkedInAdsConnector(
        "c-li", "t1", {"access_token": "tok", "ad_account_id": "123", "currency": "GBP"}, {}
    )
    captured = _install_capture(conn)

    await conn._live_backfill(date(2026, 1, 15), date(2026, 1, 15))

    assert len(captured) == 1
    m = captured[0]
    assert m.currency == "GBP"
    assert m.currency != "USD"
    assert m.spend == Decimal("12.34")
    assert m.raw_dimensions["currency_source"] == "provider"


async def test_x_uses_account_currency_from_config(monkeypatch):
    # X account-level stats do not echo a currency; source it from config.
    resp = _Resp(
        json_data={
            "data": [
                {
                    "id_data": [
                        {
                            "metrics": {
                                "billed_charge_local_micro": [12_340_000],
                                "impressions": [100],
                                "clicks": [5],
                            }
                        }
                    ]
                }
            ]
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _SingleGetClient(resp))

    conn = x_ads.XAdsConnector(
        "c-x", "t1", {"access_token": "tok", "account_id": "acc1", "currency": "JPY"}, {}
    )
    captured = _install_capture(conn)

    await conn._live_backfill(date(2026, 1, 15), date(2026, 1, 15))

    assert len(captured) == 1
    m = captured[0]
    assert m.currency == "JPY"
    assert m.currency != "USD"
    assert m.spend == Decimal("12.34")
    assert m.raw_dimensions["currency_source"] == "provider"


async def test_reddit_preserves_row_currency(monkeypatch):
    campaigns_resp = _Resp(json_data={"data": {"campaigns": [{"id": "cmp1", "name": "R1"}]}})
    report_resp = _Resp(
        json_data={
            "data": {
                "rows": [
                    {
                        "date": "2026-01-15",
                        "spend": 1234,  # cents
                        "impressions": 100,
                        "clicks": 5,
                        "currency": "CAD",
                    }
                ]
            }
        }
    )

    class _RedditClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            if url.endswith("/report"):
                return report_resp
            return campaigns_resp

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _RedditClient())

    conn = reddit_ads.RedditAdsConnector(
        "c-rd", "t1", {"access_token": "tok", "account_id": "acc1"}, {}
    )
    captured = _install_capture(conn)

    await conn._live_backfill(date(2026, 1, 15), date(2026, 1, 15))

    assert len(captured) == 1
    m = captured[0]
    assert m.currency == "CAD"
    assert m.currency != "USD"
    assert m.spend == Decimal("12.34")  # 1234 cents -> 12.34
    assert m.raw_dimensions["currency_source"] == "provider"


async def test_microsoft_end_to_end_currency_and_no_float_rounding(monkeypatch):
    import asyncio

    csv_report = (
        "TimePeriod,CampaignId,CampaignName,CurrencyCode,Impressions,Clicks,Spend\n"
        "2026-01-15,111,Camp One,EUR,1000,50,12345678901234567.89\n"
    )

    class _MSClient:
        def __init__(self, csv_text):
            self._csv = csv_text

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None, data=None):
            if "SubmitGenerateReport" in url:
                return _Resp(json_data={"ReportRequestId": "rid-1"})
            # OAuth token exchange
            return _Resp(json_data={"access_token": "tok"})

        async def get(self, url, headers=None, params=None):
            if "PollGenerateReport" in url:
                return _Resp(
                    json_data={
                        "ReportRequestStatus": {
                            "Status": "Success",
                            "ReportDownloadUrl": "https://dl.example/report",
                        }
                    }
                )
            return _Resp(text=self._csv)

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _MSClient(csv_report))

    async def _noop_sleep(*a, **k):
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    conn = microsoft_ads.MicrosoftAdsConnector(
        "c-ms",
        "t1",
        {"account_id": "acc1", "customer_id": "cust1", "developer_token": "dev"},
        {},
    )
    captured = _install_capture(conn)

    await conn._live_backfill(date(2026, 1, 15), date(2026, 1, 15))

    assert len(captured) == 1
    m = captured[0]
    # Currency comes from the report's CurrencyCode column, not hardcoded USD.
    assert m.currency == "EUR"
    assert m.currency != "USD"
    assert m.raw_dimensions["currency_source"] == "provider"
    # Money preserved to full native precision (float would have rounded).
    assert m.spend == Decimal("12345678901234567.89")
    assert m.spend != Decimal(str(float("12345678901234567.89")))
