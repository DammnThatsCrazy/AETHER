"""Certification fixtures: scrubbed sandbox payloads plus what they must map to."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from actions.agent_correlation.mappers._common import _SHOPIFY_GID, _STRIPE_ID
from shared.integration_contracts.correlation_token import extract_correlation_tokens

FIXTURE_SCHEMA_VERSION: Literal["1"] = "1"
FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "agent_correlation" / "fixtures" / "sandbox"

Origin = Literal["sandbox_recorded"]


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_count: int
    roles: list[str]
    object_types: list[str] = Field(default_factory=list)
    tokens: int = 0
    # Digest of the observations the RAW payload mapped to at record time.
    # Replay of the scrubbed record must produce the same digest, proving
    # scrubbing removed nothing the mapper reads.
    observation_digest: str
    # Link decisions observed live at record time, e.g. the payment joining the
    # certification task by token.
    links: list[dict[str, str]] = Field(default_factory=list)


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = FIXTURE_SCHEMA_VERSION
    provider: str
    kind: str
    origin: Origin
    recorder: str
    recorded_at: str
    provider_api: dict[str, str]
    realm: Literal["test"]
    account_bindings: dict[str, dict[str, str]] = Field(default_factory=dict)
    record: dict[str, Any]
    record_sha256: str
    expected: Expected
    # A per-recording key for the certification tenant only, so the token link
    # replays deterministically. It signs nothing outside certification.
    certification: Optional[dict[str, Any]] = None

    def path(self, root: Path = FIXTURE_ROOT) -> Path:
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{self.recorder}-{self.record_sha256[:12]}")
        return root / self.provider / self.kind / f"{stem}.json"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def reduce_free_text(value: Any) -> str:
    """Keep only what mappers read from free text: tokens and provider object IDs."""
    if not isinstance(value, str):
        return ""
    kept: list[str] = list(extract_correlation_tokens(value))
    kept += [m.group(0) for m in _SHOPIFY_GID.finditer(value)]
    kept += [m.group(0) for m in _STRIPE_ID.finditer(value)]
    return " ".join(dict.fromkeys(kept))


# Allowlists of the fields each mapper reads. ``"*text"`` reduces free text;
# ``"*map"`` keeps keys but reduces values; nested dicts describe sub-objects;
# ``[spec]`` applies a spec to each list element.
_SCRUB: dict[tuple[str, str], Any] = {
    ("shopify", "order"): {
        "id": 1, "admin_graphql_api_id": 1, "updated_at": 1, "created_at": 1, "app_id": 1, "user_id": 1,
        "note": "*text", "tags": "*text", "note_attributes": [{"name": 1, "value": "*text"}],
    },
    ("shopify", "inventory_level"): {
        "inventory_item_id": 1, "location_id": 1, "available": 1, "updated_at": 1, "admin_graphql_api_id": 1,
    },
    ("shopify", "product"): {
        "id": 1, "admin_graphql_api_id": 1, "updated_at": 1, "created_at": 1, "tags": "*text",
        "variants": [{"id": 1, "inventory_item_id": 1}],
    },
    ("shopify", "product_graphql"): {
        "id": 1, "updatedAt": 1, "createdAt": 1, "tags": "*text",
        "variants": {"nodes": [{"id": 1, "inventoryItem": {"id": 1}}]},
    },
    ("shopify", "inventory_level_graphql"): {
        "id": 1, "updatedAt": 1, "item": {"id": 1}, "location": {"id": 1},
    },
    ("shopify", "order_graphql"): {
        "id": 1, "updatedAt": 1, "createdAt": 1, "note": "*text", "tags": "*text",
        "customAttributes": [{"key": 1, "value": "*text"}], "app": {"id": 1}, "staffMember": {"id": 1},
    },
    ("stripe", "event"): {
        "id": 1, "type": 1, "created": 1, "livemode": 1, "account": 1, "context": 1, "api_version": 1,
        "data": {"object": {"object": 1, "id": 1, "payment_intent": 1, "charge": 1, "status": 1,
                            "livemode": 1, "metadata": "*map", "description": "*text"}},
    },
    ("ramp", "transaction"): {
        "id": 1, "user_transaction_time": 1, "card_id": 1, "state": 1, "memo": "*text",
        "card_holder": {"user_id": 1},
    },
    ("ramp", "limit"): {
        "id": 1, "created_at": 1, "updated_at": 1, "card_id": 1, "user_id": 1, "display_name": "*text",
        "memo": "*text", "cards": [{"card_id": 1, "id": 1}], "users": [{"user_id": 1, "id": 1}],
    },
    ("cloudflare", "ai_gateway_log"): {
        "id": 1, "created_at": 1, "provider": 1, "model": 1, "success": 1, "metadata": "*map",
    },
    ("openai", "export"): {
        "data": [{
            "object": 1, "id": 1, "trace_id": 1, "parent_id": 1, "started_at": 1, "ended_at": 1,
            "workflow_name": 1, "group_id": 1, "metadata": "*map",
            "span_data": {"type": 1, "name": 1, "input": "*text", "output": "*text"},
        }],
    },
}


def _apply(spec: Any, value: Any) -> Any:
    if spec == 1:
        return value
    if spec == "*text":
        if isinstance(value, list):
            return [reduce_free_text(v) for v in value]
        return reduce_free_text(value)
    if spec == "*map":
        if isinstance(value, Mapping):
            return {str(k): reduce_free_text(v) for k, v in value.items()}
        return reduce_free_text(value) if isinstance(value, str) else None
    if isinstance(spec, list):
        if not isinstance(value, list):
            return []
        return [_apply(spec[0], item) for item in value[:50]]
    if isinstance(spec, dict):
        if not isinstance(value, Mapping):
            return None
        return {k: _apply(sub, value[k]) for k, sub in spec.items() if k in value}
    raise ValueError(f"bad scrub spec {spec!r}")


def scrub(provider: str, kind: str, record: Mapping[str, Any]) -> dict[str, Any]:
    spec = _SCRUB.get((provider, kind))
    if spec is None:
        raise ValueError(f"no scrub allowlist for {provider}/{kind}; refusing to store an unscrubbed payload")
    return _apply(spec, record)  # type: ignore[return-value]


def load_fixtures(root: Path = FIXTURE_ROOT) -> list[Fixture]:
    if not root.exists():
        return []
    return [Fixture.model_validate_json(p.read_text()) for p in sorted(root.rglob("*.json"))]


def write_fixture(fixture: Fixture, root: Path = FIXTURE_ROOT) -> Path:
    path = fixture.path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    return path
