"""Strict, local telemetry contracts for delivery and verification evidence.

This module validates event shape only.  It does not send events, persist them,
or select a hosted telemetry provider.  Keeping the contract at the event
boundary means local tooling and a future exporter have the same vocabulary and
unknown or accidentally sensitive fields cannot silently escape into either.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "config" / "telemetry_contracts.json"
SCHEMA_VERSION = 1
_EVENT_KEYS = {"id", "description", "producer", "data_classification", "fields"}
_REGISTRY_KEYS = {"schema_version", "canonical_source", "events"}
_FIELD_KEYS = {"type", "items", "required", "enum"}
_TYPES = {"string", "boolean", "integer", "number", "array"}


class TelemetryContractError(ValueError):
    """A telemetry registry or event violates its repository contract."""


@dataclass(frozen=True)
class TelemetryField:
    name: str
    type: str
    required: bool
    items: str | None = None
    enum: tuple[str, ...] = ()


@dataclass(frozen=True)
class TelemetryEvent:
    id: str
    description: str
    producer: str
    data_classification: str
    fields: Mapping[str, TelemetryField]


@dataclass(frozen=True)
class TelemetryRegistry:
    schema_version: int
    canonical_source: str
    events: Mapping[str, TelemetryEvent]

    def event(self, event_id: str) -> TelemetryEvent:
        try:
            return self.events[event_id]
        except KeyError as exc:
            raise TelemetryContractError(f"unknown telemetry event {event_id!r}") from exc

    def validate_payload(self, event_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and return a JSON-safe shallow copy of event data."""
        event = self.event(event_id)
        if not isinstance(payload, Mapping):
            raise TelemetryContractError(f"event {event_id!r}.data must be an object")
        unknown = sorted(set(payload) - set(event.fields))
        if unknown:
            raise TelemetryContractError(
                f"event {event_id!r}.data has unknown field(s): {', '.join(unknown)}"
            )
        missing = sorted(
            name for name, field in event.fields.items() if field.required and name not in payload
        )
        if missing:
            raise TelemetryContractError(
                f"event {event_id!r}.data is missing required field(s): {', '.join(missing)}"
            )
        for name, value in payload.items():
            _validate_field(value, event.fields[name], f"event {event_id!r}.data.{name}")
        return dict(payload)

    def build_event(
        self,
        event_id: str,
        payload: Mapping[str, Any],
        *,
        event_id_value: str | None = None,
        occurred_at: str | None = None,
        producer: str | None = None,
    ) -> dict[str, Any]:
        """Build one validated envelope without performing any I/O."""
        event = self.event(event_id)
        if producer is not None and producer != event.producer:
            raise TelemetryContractError(
                f"event {event_id!r} producer override {producer!r} does not match registered producer {event.producer!r}"
            )
        data = self.validate_payload(event_id, payload)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id_value or f"tel_{uuid.uuid4().hex}",
            "event_name": event_id,
            "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
            "producer": event.producer,
            "data": data,
        }
        validate_envelope(envelope, self)
        return envelope


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TelemetryContractError(f"{where} must be a non-empty string")
    return value


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TelemetryContractError(f"{where} must be an object")
    return value


def _validate_field(value: Any, field: TelemetryField, where: str) -> None:
    validators = {
        "string": lambda v: isinstance(v, str),
        "boolean": lambda v: isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
    }
    valid = validators[field.type](value)
    if not valid:
        raise TelemetryContractError(f"{where} must be a {field.type}")
    if field.type == "array" and field.items:
        for index, item in enumerate(value):
            if not validators[field.items](item):
                raise TelemetryContractError(f"{where}[{index}] must be a {field.items}")
    if field.enum and value not in field.enum:
        raise TelemetryContractError(f"{where} must be one of {list(field.enum)!r}")


def validate_registry(data: Any) -> TelemetryRegistry:
    top = _require_mapping(data, "telemetry registry")
    unknown = sorted(set(top) - _REGISTRY_KEYS)
    if unknown:
        raise TelemetryContractError(f"telemetry registry has unknown key(s): {', '.join(unknown)}")
    if top.get("schema_version") != SCHEMA_VERSION:
        raise TelemetryContractError("telemetry registry.schema_version must be 1")
    canonical_source = _require_string(
        top.get("canonical_source"), "telemetry registry.canonical_source"
    )
    raw_events = top.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise TelemetryContractError("telemetry registry.events must be a non-empty list")
    events: dict[str, TelemetryEvent] = {}
    for index, raw in enumerate(raw_events):
        item = _require_mapping(raw, f"telemetry registry.events[{index}]")
        unknown = sorted(set(item) - _EVENT_KEYS)
        if unknown:
            raise TelemetryContractError(
                f"telemetry registry.events[{index}] has unknown key(s): {', '.join(unknown)}"
            )
        event_id = _require_string(item.get("id"), f"telemetry registry.events[{index}].id")
        if event_id in events:
            raise TelemetryContractError(f"duplicate telemetry event id {event_id!r}")
        description = _require_string(item.get("description"), f"event {event_id}.description")
        producer = _require_string(item.get("producer"), f"event {event_id}.producer")
        classification = _require_string(
            item.get("data_classification"), f"event {event_id}.data_classification"
        )
        if classification != "operational_metadata":
            raise TelemetryContractError(
                f"event {event_id}.data_classification must be operational_metadata"
            )
        raw_fields = _require_mapping(item.get("fields"), f"event {event_id}.fields")
        if not raw_fields:
            raise TelemetryContractError(f"event {event_id}.fields must not be empty")
        fields: dict[str, TelemetryField] = {}
        for name, raw_field in raw_fields.items():
            field_name = _require_string(name, f"event {event_id}.fields key")
            spec = _require_mapping(raw_field, f"event {event_id}.fields.{field_name}")
            unknown = sorted(set(spec) - _FIELD_KEYS)
            if unknown:
                raise TelemetryContractError(
                    f"event {event_id}.fields.{field_name} has unknown key(s): {', '.join(unknown)}"
                )
            field_type = _require_string(
                spec.get("type"), f"event {event_id}.fields.{field_name}.type"
            )
            if field_type not in _TYPES:
                raise TelemetryContractError(
                    f"event {event_id}.fields.{field_name}.type is invalid"
                )
            required = spec.get("required")
            if not isinstance(required, bool):
                raise TelemetryContractError(
                    f"event {event_id}.fields.{field_name}.required must be boolean"
                )
            items = spec.get("items")
            if field_type == "array":
                if items not in {"string", "boolean", "integer", "number"}:
                    raise TelemetryContractError(
                        f"event {event_id}.fields.{field_name}.items must name a scalar type"
                    )
            elif items is not None:
                raise TelemetryContractError(
                    f"event {event_id}.fields.{field_name}.items is only valid for arrays"
                )
            enum = spec.get("enum", [])
            if not isinstance(enum, list) or not all(
                isinstance(value, str) and value for value in enum
            ):
                raise TelemetryContractError(
                    f"event {event_id}.fields.{field_name}.enum must be a list of strings"
                )
            if len(enum) != len(set(enum)):
                raise TelemetryContractError(
                    f"event {event_id}.fields.{field_name}.enum must be unique"
                )
            if enum and field_type != "string":
                raise TelemetryContractError(
                    f"event {event_id}.fields.{field_name}.enum requires a string field"
                )
            fields[field_name] = TelemetryField(
                field_name, field_type, required, items, tuple(enum)
            )
        events[event_id] = TelemetryEvent(event_id, description, producer, classification, fields)
    return TelemetryRegistry(SCHEMA_VERSION, canonical_source, events)


def load_registry(path: str | Path = DEFAULT_REGISTRY) -> TelemetryRegistry:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TelemetryContractError(f"cannot read telemetry registry {resolved}: {exc}") from exc
    return validate_registry(raw)


def validate_envelope(
    envelope: Mapping[str, Any], registry: TelemetryRegistry | None = None
) -> None:
    """Fail closed on envelope metadata and the event's declared data shape."""
    registry = registry or load_registry()
    required = {"schema_version", "event_id", "event_name", "occurred_at", "producer", "data"}
    unknown = sorted(set(envelope) - required)
    missing = sorted(required - set(envelope))
    if unknown:
        raise TelemetryContractError(f"telemetry envelope has unknown key(s): {', '.join(unknown)}")
    if missing:
        raise TelemetryContractError(
            f"telemetry envelope is missing field(s): {', '.join(missing)}"
        )
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise TelemetryContractError("telemetry envelope.schema_version must be 1")
    for key in ("event_id", "event_name", "producer"):
        _require_string(envelope.get(key), f"telemetry envelope.{key}")
    occurred_at = _require_string(envelope.get("occurred_at"), "telemetry envelope.occurred_at")
    try:
        datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TelemetryContractError("telemetry envelope.occurred_at must be ISO-8601") from exc
    event = registry.event(str(envelope["event_name"]))
    if envelope["producer"] != event.producer:
        raise TelemetryContractError("telemetry envelope.producer does not match the registered event producer")
    registry.validate_payload(str(envelope["event_name"]), envelope["data"])


__all__ = [
    "DEFAULT_REGISTRY",
    "TelemetryContractError",
    "TelemetryEvent",
    "TelemetryField",
    "TelemetryRegistry",
    "build_event",
    "load_registry",
    "validate_envelope",
    "validate_registry",
]


def build_event(event_name: str, payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Convenience wrapper for callers that use the canonical registry."""
    return load_registry().build_event(event_name, payload, **kwargs)
