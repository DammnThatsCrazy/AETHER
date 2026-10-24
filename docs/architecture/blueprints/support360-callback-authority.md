# Support360 callback schedule and execution authority

This slice adds the canonical callback schedule and observed execution-event
authority used by the Support360 `callbacks` slot. The callback authority is
not a caller for the customer, an agent execution ledger, or a business outcome
authority. It records source-asserted schedule and lifecycle events linked to
one exact canonical support case.

## Ownership and write path

`services/api/journeys/support360/callbacks.py` owns typed callback inputs, the
tenant-scoped `SupportCallbackRepository`, and the
`SupportCallbackIngestionService`. `POST /v1/support/cases/callbacks/ingest`
requires tenant write permission and a verified provider connection. A callback
must refer to an existing canonical SupportCase created through that same
tenant, connection, and provider. A source callback identifier is scoped to its
provider connection; AETHER generates the canonical callback UUID.

Schedule, reschedule, attempt, completion, failure, and cancellation are
allow-listed event types. Every accepted update appends a
`support_callback_events` row with source event ID, source occurrence time,
receipt time, optional scheduled effective time, application status, and
evidence references. The current callback row is a projection of those events.
The repository accepts idempotent replay of unchanged source events, rejects
changed reuse, disallows invalid lifecycle transitions, and retains stale
source events without regressing current state. The database rejects event-row
updates; the parent case's retention and legal-hold behavior governs eventual
record deletion.

The callback event also names the exact latest canonical case event known at
ingestion. Database foreign keys bind both callback and case event rows to the
same tenant, case, and provider connection. Stored evidence references identify
the canonical callback, canonical case, linked case event, callback provider
event, and provider connection. No raw provider payload or message content is
stored.

The ingress verifies tenant write permission and the provider connection's
verified state, then binds the event to the exact case owned by that connection.
It does not validate a provider webhook signature or independently authenticate
the upstream event. The record therefore proves that the tenant-authorized
ingress accepted a source assertion under a verified connection; provider
origin and the identity of the human or agent writer remain unverified.

## Read and projection behavior

The Support360 provider reads callbacks by exact tenant and canonical case ID,
or resolves a canonical callback ID within tenant scope before joining its
exact canonical case. It rechecks provider, connection, case, callback, event,
and case-event evidence before emitting callback data. Missing or inconsistent
authority/provenance yields `unknown` without callback values.

Callback lists are capped at 100 callbacks and 50 events per callback. A direct
callback subject is capped at 50 events. Truncation is reported as partial read
completeness and a degraded slot. A complete current-store read does not prove
that the provider delivered all source history, so `sourceHistoryComplete`
remains false. The freshness state remains unknown because this slice has no
callback-specific freshness service level or source watermark.

The claim is limited to an observation: tenant-authorized ingress accepted a
source-asserted callback schedule or execution event under the verified
provider connection for the exact canonical support case. It does not establish
that a call was placed by AETHER, that a human or agent performed it, that the
callback reached the customer, or that a business outcome followed.

## Projection binding

The existing `support360.callbacks` product slot is bound to the implemented
Support360 provider and callback authorities:

```json
{
  "id": "callbacks",
  "requirement": "required",
  "description": "Canonical callback schedule and execution records joined to the exact tenant, support case, provider connection, and retained callback events.",
  "canonicalAuthorityRefs": [
    "support_callbacks",
    "support_callback_events",
    "support_cases",
    "support_case_events",
    "provider_connections",
    "evidence"
  ],
  "projectionBindings": [
    {
      "projectionId": "support360",
      "role": "primary",
      "subjectKinds": ["support_case", "callback"],
      "sectionIds": ["state", "timeline", "evidence"]
    }
  ],
  "partialImplementationReason": "callback_schedule_and_execution_authority_is_tenant_case_connection_scoped_but_upstream_provider_origin_and_actor_attribution_are_unverified; source_history_completeness_and_freshness_remain_unknown"
}
```

This binding covers only the callback slot. It does not complete Support360's
other required slots or establish agent assignment, agent execution, SLA,
communications, risk/contagion, or value observability joins.
