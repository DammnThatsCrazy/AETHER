"""Certification harness: record → scrub → fixture → replay → report.

The simulated transport here tests the harness itself. Fixtures it writes go to
a temporary directory and never count as certification: only recordings from a
real provider sandbox committed under ``fixtures/sandbox`` do.
"""

from __future__ import annotations

import json

import httpx
import pytest

from actions.agent_correlation.certification import fixtures as fx
from actions.agent_correlation.certification.record import record_provider
from actions.agent_correlation.certification.runner import (
    REPORT_PATH,
    build_report,
    render_report,
    replay,
    replay_all,
)

ACCOUNT = "acct_1SandboxAbc"


def _stripe_transport(*, livemode: bool = False, created: list | None = None) -> httpx.MockTransport:
    state: dict = {"pi": None, "re": None, "token": None}
    created = created if created is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/balance":
            return httpx.Response(200, json={"object": "balance", "livemode": livemode})
        if path == "/v1/account":
            return httpx.Response(200, json={"id": ACCOUNT, "object": "account"})
        if path == "/v1/payment_intents":
            form = dict(httpx.QueryParams(request.content.decode()))
            state["token"] = form["metadata[aether_correlation]"]
            state["pi"] = "pi_3SandboxPaymentAbc"
            created.append("payment_intent")
            return httpx.Response(200, json={"id": state["pi"], "object": "payment_intent", "livemode": False})
        if path == "/v1/refunds":
            state["re"] = "re_3SandboxRefundAbcd"
            created.append("refund")
            return httpx.Response(200, json={"id": state["re"], "object": "refund"})
        if path == "/v1/events":
            types = request.url.params.get_list("types[]")
            if "payment_intent.succeeded" in types:
                obj = {"object": "payment_intent", "id": state["pi"], "status": "succeeded", "livemode": False,
                       "metadata": {"aether_correlation": state["token"]},
                       "description": "Aether correlation certification", "receipt_email": "jane@example.com"}
                event = {"id": "evt_pi_1", "type": "payment_intent.succeeded", "created": 1763121600,
                         "livemode": False, "api_version": "2026-10-28", "data": {"object": obj}}
            else:
                obj = {"object": "refund", "id": state["re"], "payment_intent": state["pi"], "charge": "ch_3SandboxChargeAb",
                       "metadata": {"aether_correlation": state["token"]}, "status": "succeeded"}
                event = {"id": "evt_re_1", "type": "refund.created", "created": 1763121601,
                         "livemode": False, "api_version": "2026-10-28", "data": {"object": obj}}
            return httpx.Response(200, json={"data": [event]})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def test_scrub_keeps_only_mapped_fields_and_reduces_free_text() -> None:
    record = {"id": "evt", "type": "x", "created": 1, "livemode": False, "request": {"id": "req_1"},
              "data": {"object": {"object": "charge", "id": "ch_1Abcdefghij", "receipt_email": "a@b.c",
                                  "billing_details": {"name": "Jane"},
                                  "description": "call Jane at 555 about pi_1Abcdefghij",
                                  "metadata": {"note": "VIP customer"}}}}
    out = fx.scrub("stripe", "event", record)
    assert "request" not in out
    obj = out["data"]["object"]
    assert "receipt_email" not in obj and "billing_details" not in obj
    assert obj["description"] == "pi_1Abcdefghij"
    assert obj["metadata"] == {"note": ""}
    with pytest.raises(ValueError, match="refusing"):
        fx.scrub("stripe", "unknown_kind", record)


@pytest.mark.asyncio
async def test_record_writes_scrubbed_fixtures_that_replay_with_their_token_link(tmp_path) -> None:
    async with httpx.AsyncClient(transport=_stripe_transport()) as client:
        run = await record_provider("stripe", client=client, root=tmp_path)
    assert run.failures == [] and len(run.written) == 2
    loaded = fx.load_fixtures(tmp_path)
    assert {f.recorder for f in loaded} == {"stripe.payment_intent_succeeded", "stripe.refund_created"}
    for fixture in loaded:
        assert fixture.origin == "sandbox_recorded" and fixture.realm == "test"
        text = json.dumps(fixture.record)
        assert "jane@example.com" not in text
        # The live run joined the payment to the certification task by token, and replay reproduces it.
        assert fixture.expected.links and fixture.expected.links[0]["key_kind"] == "aether_correlation_token"
        result = await replay(fixture)
        assert result.passed, result.failures
    report = build_report(await replay_all(loaded))
    stripe_row = next(r for r in report["kinds"] if r["provider"] == "stripe")
    assert stripe_row["status"] == "sandbox_certified" and stripe_row["fixtures"] == 2


@pytest.mark.asyncio
async def test_live_stripe_key_is_refused_before_anything_is_created(tmp_path) -> None:
    created: list = []
    async with httpx.AsyncClient(transport=_stripe_transport(livemode=True, created=created)) as client:
        run = await record_provider("stripe", client=client, root=tmp_path)
    assert created == []
    assert run.written == [] and "not a test-mode key" in run.failures[0]


@pytest.mark.asyncio
async def test_tampered_fixture_fails_replay(tmp_path) -> None:
    async with httpx.AsyncClient(transport=_stripe_transport()) as client:
        await record_provider("stripe", client=client, root=tmp_path)
    fixture = fx.load_fixtures(tmp_path)[0]
    tampered = fixture.model_copy(update={"record": {**fixture.record, "id": "evt_other"}})
    result = await replay(tampered)
    assert not result.passed
    report = build_report([result])
    assert next(r for r in report["kinds"] if r["provider"] == "stripe")["status"] == "failed"


@pytest.mark.asyncio
async def test_missing_credentials_skip_instead_of_certifying(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHOPIFY_SANDBOX_SHOP", raising=False)
    run = await record_provider("shopify", root=tmp_path)
    assert run.skipped == "SHOPIFY_SANDBOX_SHOP is not set" and run.written == []


@pytest.mark.asyncio
async def test_committed_fixtures_replay_and_the_report_is_current() -> None:
    """Every committed sandbox fixture replays, and the committed report matches them."""
    results = await replay_all()
    assert all(r.passed for r in results), [(r.fixture.recorder, r.failures) for r in results if not r.passed]
    assert REPORT_PATH.read_text() == render_report(build_report(results))


def test_report_never_certifies_without_recordings() -> None:
    report = build_report([])
    statuses = {(r["provider"], r["kind"]): r["status"] for r in report["kinds"]}
    assert statuses[("stripe", "event")] == "uncertified"
    assert statuses[("cloudflare", "http_request")] == "not_recordable"
    assert statuses[("aether_mcp", "task_registered")] == "first_party"


def test_scrub_keeps_long_scope_lists_that_change_the_observation() -> None:
    """Found by certifying a real Shopify installation with 65 access scopes."""
    from actions.agent_correlation.certification.runner import context_for, expected_from
    from actions.agent_correlation.mappers import map_record

    record = {"observed_at": "2026-11-15T18:40:00Z", "installation": {
        "id": "gid://shopify/AppInstallation/1", "app": {"id": "gid://shopify/App/2"},
        "accessScopes": [{"handle": f"read_scope_{i:03d}"} for i in range(65)]}}
    ctx = context_for("t", {"shopify": {"source_account_key": "s.myshopify.com", "source_account_realm": "test"}})
    raw = expected_from(map_record("shopify", "access_grant_graphql", ctx, record))
    scrubbed = expected_from(map_record("shopify", "access_grant_graphql", ctx, fx.scrub("shopify", "access_grant_graphql", record)))
    assert raw["observation_digest"] == scrubbed["observation_digest"]


def test_real_shopify_grant_and_order_follow_the_standing_authority_rule() -> None:
    """Uses the recorded installation and order: same app, ordered in time."""
    from actions.agent_correlation.certification.runner import context_for
    from actions.agent_correlation.mappers import map_record
    from shared.integration_contracts.correlation import correlate

    by_kind = {f.kind: f for f in fx.load_fixtures() if f.provider == "shopify"}
    grant_fx, order_fx = by_kind["access_grant_graphql"], by_kind["order_graphql"]
    ctx = context_for("t", grant_fx.account_bindings)
    (grant,) = map_record("shopify", "access_grant_graphql", ctx, grant_fx.record)
    (order,) = map_record("shopify", "order_graphql", ctx, order_fx.record)
    assert set(grant.actor_refs) & set(order.actor_refs)  # the order was created by the granted app
    # The order predates the observed grant: no evidence the grant was in effect.
    assert correlate(grant, order).key_kind != "provider_actor_ref"
    later = order.model_copy(update={"observation_id": "later", "occurred_at": grant.occurred_at.replace(year=2027)})
    verdict = correlate(grant, later)
    assert verdict.key_kind == "provider_actor_ref" and verdict.status == "candidate"
