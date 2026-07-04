from packages.python.aether_agentic import (
    AgenticObservationClient,
    AgenticObservationInput,
    build_agentic_observation,
    to_ingestion_event,
)


def test_build_agentic_observation_contract_v2_no_execution_and_no_token():
    event = build_agentic_observation(
        AgenticObservationInput(
            tenant_id="tenant-a",
            event_type="agent_tool_invocation_observed",
            agent={"agent_id": "agent-1"},
            correlation={"invocation_id": "invoke-1"},
            mcp={"tool_name": "x.create_post", "arguments_policy": "metadata_only"},
            authorization={"authorization_id": "auth-1", "credential_ref": "vault://auth-1", "scopes": ["tweet.write"]},
            object={"object_type": "tool", "object_id": "tool-1"},
            action={"name": "tool_invocation_observed", "status": "observed"},
            economics={"amount": 1, "currency": "USD"},
        )
    )

    assert event["schema_version"] == "2.0"
    assert event["event_name"] == event["event_type"]
    assert event["economics"]["is_execution_by_aether"] is False
    assert event["authorization"]["credential_ref"] == "vault://auth-1"
    assert "access_token" not in event["authorization"]


def test_to_ingestion_event_preserves_observation_only_contract():
    event = build_agentic_observation(
        {
            "tenant_id": "tenant-a",
            "event_type": "agent_activity_observed",
            "object": {"object_type": "agent", "object_id": "agent-1"},
            "action": {"name": "agent_observed", "status": "observed"},
        }
    )
    ingestion = to_ingestion_event(event)

    assert ingestion["type"] == "agent_activity_observed"
    assert ingestion["message_id"] == event["event_id"]
    assert ingestion["properties"]["execution_by_aether"] is False
    assert ingestion["properties"]["agentic_contract_version"] == "2.0"


def test_agentic_client_queues_named_helpers():
    client = AgenticObservationClient()

    client.observe_mcp_connection(tenant_id="tenant-a", connection_id="conn-1", server_name="x-tools")
    client.observe_authorization(tenant_id="tenant-a", authorization_id="auth-1", external_account_id="acct-1", scopes=["tweet.write"])
    client.observe_provider_action(tenant_id="tenant-a", provider_action_id="act-1", provider_request_id="req-1", external_object_id="obj-1")
    client.observe_provider_verification(tenant_id="tenant-a", verification_id="ver-1", status="provider_confirmed", provider_request_id="req-1", external_object_id="obj-1")

    events = client.drain()
    assert [event["type"] for event in events] == [
        "agent_mcp_connection_observed",
        "agent_permission_observed",
        "agent_tool_invocation_observed",
        "agent_activity_observed",
    ]
    assert client.queue_depth == 0
    assert all(event["properties"]["execution_by_aether"] is False for event in events)
