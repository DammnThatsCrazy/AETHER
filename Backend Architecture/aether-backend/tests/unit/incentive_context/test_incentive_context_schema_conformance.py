"""Structural conformance: every resolver-produced context validates against the
M1 ``incentive-context.schema.json`` with a real Draft 2020-12 validator.

``additionalProperties: false`` is enforced by the validator, so a context whose
serialized dict carries anything the schema does not declare fails here — this
is the guarantee that the resolver only ever emits canonical contexts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMA_PATH = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "incentive-context.schema.json"
)

from services.incentive_context.canonical import INCENTIVE_STATUSES  # noqa: E402
from services.incentive_context.models import IncentiveContext  # noqa: E402
from services.incentive_context.resolver import (  # noqa: E402
    CampaignEvidence,
    IncentiveAssessment,
    IncentiveSignal,
    resolve_incentive_context,
)

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
_WINDOW_CAMPAIGN = CampaignEvidence(
    campaign_ref="cmp-w",
    reward_program=True,
    start_at="2026-04-01T00:00:00+00:00",
    end_at="2026-06-01T00:00:00+00:00",
    source_ref="cmp-row-w",
)


@pytest.fixture(scope="module")
def validator() -> jsonschema.Draft202012Validator:
    with SCHEMA_PATH.open() as fh:
        schema = json.load(fh)
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )


def _resolve(**overrides):
    kwargs = dict(
        tenant_id="ten-1",
        social_identity_ref="si-1",
        interaction_ref="in-1",
        source_scope="tenant_connected",
        evidence_basis="provider_api",
        computed_at=NOW,
    )
    kwargs.update(overrides)
    return resolve_incentive_context(**kwargs)


def _all_seven_status_contexts():
    """One produced context per valid status (the full honest-state ladder)."""
    return {
        "verified": _resolve(
            interaction_ref="in-v",
            signals=[IncentiveSignal(kind="economic_transfer_verified", ref="econ-v")],
        ),
        "declared": _resolve(
            interaction_ref="in-d",
            signals=[IncentiveSignal(kind="sponsorship_declared", ref="spo-d")],
        ),
        "observed": _resolve(
            interaction_ref="in-o",
            campaign_ref="cmp-w",
            campaign=_WINDOW_CAMPAIGN,
            activity_occurred_at="2026-05-01T00:00:00Z",
            timeline=[
                datetime(2026, 3, 1, tzinfo=timezone.utc),
                datetime(2026, 5, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 1, tzinfo=timezone.utc),
            ],
        ),
        "suspected": _resolve(
            interaction_ref="in-s",
            campaign=_WINDOW_CAMPAIGN,
            activity_occurred_at="2026-05-01T00:00:00Z",
            allow_temporal_suspicion=True,
        ),
        "none_observed": _resolve(
            interaction_ref="in-n",
            assessment=IncentiveAssessment(
                scope="bounded_enumeration", source_refs=("reg://campaigns",)
            ),
        ),
        "unknown": _resolve(interaction_ref="in-u"),
        "not_applicable": _resolve(
            interaction_ref="in-na",
            assessment=IncentiveAssessment(scope="not_applicable"),
        ),
    }


@pytest.mark.parametrize("status", INCENTIVE_STATUSES)
def test_every_status_is_schema_conformant(validator, status: str) -> None:
    context = _all_seven_status_contexts()[status]
    assert context.status == status
    data = context.to_dict()
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    assert not errors, f"context status={status} violates schema: {errors}"


def test_context_is_incentive_context_instance() -> None:
    assert isinstance(_resolve(), IncentiveContext)


def test_to_dict_declares_exact_schema_keys() -> None:
    data = _resolve().to_dict()
    with SCHEMA_PATH.open() as fh:
        schema = json.load(fh)
    declared = set(schema["properties"].keys())
    assert set(data.keys()) == declared


def test_direct_incentive_is_a_concrete_boolean() -> None:
    for status, ctx in _all_seven_status_contexts().items():
        assert isinstance(ctx.direct_incentive, bool), status
