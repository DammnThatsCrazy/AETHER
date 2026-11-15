"""Cloudflare: network observer for zones and gateways the tenant controls.

Inputs:

* ``ai_gateway_log`` — an AI Gateway log entry (``id``, ``created_at``,
  ``provider``, ``model``, ``metadata``). An agent can send its correlation
  token as gateway metadata, which joins the model call to its task exactly.
* ``http_request`` — an HTTP request log row exported by the tenant (Logpush or
  a Worker). ``RayID`` and ``EdgeStartTimestamp`` are Logpush fields; the
  signed-agent fields ``signature_nonce`` and ``signature_verified`` are the
  tenant's export of the request's HTTP message signature check. A verified
  signature whose nonce the agent runtime also reports attests the traffic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from actions.agent_correlation.mappers._common import (
    MapperContext,
    MappingError,
    find_tokens,
    opt_str,
    parse_time,
    require,
)
from shared.integration_contracts.correlation import CorrelationObservation, SignedRequestRef

FAMILY = "cloudflare"


def _edge_time(value: Any) -> datetime:
    # Logpush emits EdgeStartTimestamp as RFC 3339 or as unix nanoseconds.
    if isinstance(value, int) and not isinstance(value, bool) and value > 10**14:
        return datetime.fromtimestamp(value / 1e9, tz=timezone.utc)
    return parse_time(value, field_name="EdgeStartTimestamp")


def map_ai_gateway_log(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    log_id = str(require(record, "id"))
    occurred = parse_time(record.get("created_at"), field_name="created_at")
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"cloudflare:ai_gateway_log:{log_id}",
        source_role="network_observer",
        provider_family=FAMILY,
        occurred_at=occurred,
        correlation_tokens=find_tokens(record.get("metadata")),
        infrastructure_refs=(f"cf_aig_log:{log_id}",),
    )]


def map_http_request(ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    ray_id = str(require(record, "RayID"))
    occurred = _edge_time(record.get("EdgeStartTimestamp"))
    nonce = opt_str(record.get("signature_nonce"))
    verified = record.get("signature_verified")
    if verified is not None and not isinstance(verified, bool):
        raise MappingError("signature_verified must be a boolean")
    signed = (
        SignedRequestRef(request_id=f"sig_nonce:{nonce}", signature_verified=bool(verified))
        if nonce
        else None
    )
    return [CorrelationObservation(
        tenant_id=ctx.tenant_id,
        observation_id=f"cloudflare:http_request:{ray_id}",
        source_role="network_observer",
        provider_family=FAMILY,
        occurred_at=occurred,
        signed_request=signed,
        infrastructure_refs=(f"cf_ray:{ray_id}",),
    )]


KINDS = {
    "ai_gateway_log": ("network_observer", map_ai_gateway_log),
    "http_request": ("network_observer", map_http_request),
}
