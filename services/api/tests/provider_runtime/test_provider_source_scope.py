"""Provider records resolve to an account or a manifest-declared stream scope only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from connectors.provider_runtime.rights_admission import (
    ProviderRawRightsDenied,
    provider_source_id,
    provider_stream_source_id,
)
from shared.integration_contracts.events import make_raw_record

PARTNER = "polymarket.partner.activity_stream"


def _streams(identity):
    assert identity == PARTNER
    return [SimpleNamespace(stream_id="activity")]


def _record(**overrides):
    values = dict(
        provider_identity=PARTNER, provider_record_id="a-1", payload={},
        tenant_id="tenant-1", connection_id="conn_1", account_id="", stream_id="activity",
    )
    values.update(overrides)
    return make_raw_record(**values)


def test_account_scope_wins_when_record_names_an_account():
    assert provider_source_id(_record(account_id="acct-9"), stream_lookup=_streams) == (
        "provider-account:conn_1:acct-9"
    )


def test_declared_stream_scope_for_accountless_records():
    # Scope resolution never authorizes; admission denies without a stream grant.
    assert provider_source_id(_record(), stream_lookup=_streams) == "provider-stream:conn_1:activity"


@pytest.mark.parametrize("stream_id", ["undeclared", "", None])
def test_undeclared_or_missing_stream_denies(stream_id):
    with pytest.raises(ProviderRawRightsDenied):
        provider_source_id(_record(stream_id=stream_id), stream_lookup=_streams)


def test_stream_lookup_failure_denies():
    def missing(identity):
        raise KeyError(identity)

    with pytest.raises(ProviderRawRightsDenied):
        provider_source_id(_record(), stream_lookup=missing)


def test_no_connection_wide_fallback():
    with pytest.raises(ProviderRawRightsDenied):
        provider_source_id(_record(connection_id=""), stream_lookup=_streams)
    with pytest.raises(ProviderRawRightsDenied):
        provider_stream_source_id("conn_1", " ")


def test_same_upstream_ids_under_different_connections_stay_distinct():
    a = provider_source_id(_record(connection_id="conn_a"), stream_lookup=_streams)
    b = provider_source_id(_record(connection_id="conn_b"), stream_lookup=_streams)
    assert a != b


def test_replayed_record_resolves_the_same_source_id():
    record = _record()
    replayed = record.model_copy(update={"metadata": {"replay": True}})
    assert provider_source_id(record, stream_lookup=_streams) == provider_source_id(
        replayed, stream_lookup=_streams,
    )
