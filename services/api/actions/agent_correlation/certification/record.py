"""Record sandbox payloads and turn them into verified, scrubbed fixtures."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from pathlib import Path

from actions.agent_correlation.certification.fixtures import (
    FIXTURE_ROOT,
    Expected,
    Fixture,
    digest,
    scrub,
    write_fixture,
)
from actions.agent_correlation.certification.recorders import (
    RECORDERS,
    RecorderError,
    RecorderSkipped,
    Recording,
    RecordingContext,
)
from actions.agent_correlation.certification.runner import context_for, expected_from, live_links
from actions.agent_correlation.keys import CorrelationKeyring
from actions.agent_correlation.mappers import map_record
from shared.integration_contracts.correlation_token import issue_correlation_token

CERTIFICATION_TENANT = "aether_certification"


@dataclass
class RecordRun:
    provider: str
    written: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skipped: Optional[str] = None


def _task_companion(token: str, task_ref: str, issued_at: datetime) -> Any:
    (task_obs,) = map_record("aether_mcp", "task_registered", context_for(CERTIFICATION_TENANT, {}), {
        "agent_platform": "aether_certification", "task_ref": task_ref,
        "correlation_token": token, "registered_at": issued_at.isoformat(),
    })
    return task_obs


async def fixture_from_recording(
    recording: Recording,
    *,
    keyring: CorrelationKeyring,
    companion: Any,
    recorded_at: datetime,
) -> Fixture:
    ctx = context_for(CERTIFICATION_TENANT, recording.account_bindings)
    raw_obs = map_record(recording.provider, recording.kind, ctx, recording.raw)
    expected = expected_from(raw_obs)
    links = await live_links(
        keyring, CERTIFICATION_TENANT, [companion], raw_obs,
        now=recorded_at, provider=recording.provider, kind=recording.kind,
    )
    expected["links"] = [l for l in links if l["other_observation_id"] == companion.observation_id]
    scrubbed = scrub(recording.provider, recording.kind, recording.raw)
    if expected_from(map_record(recording.provider, recording.kind, ctx, scrubbed))["observation_digest"] != expected["observation_digest"]:
        raise RecorderError(f"{recording.recorder}: scrubbing removed a field the mapper reads")
    secret = keyring.secret(keyring.signing_key_id)
    return Fixture(
        provider=recording.provider,
        kind=recording.kind,
        origin="sandbox_recorded",
        recorder=recording.recorder,
        recorded_at=recorded_at.isoformat(),
        provider_api=recording.provider_api,
        realm="test",
        account_bindings=recording.account_bindings,
        record=scrubbed,
        record_sha256=digest(scrubbed),
        expected=Expected(**expected),
        certification={
            "tenant_id": CERTIFICATION_TENANT,
            "key_id": keyring.signing_key_id,
            "key_b64": base64.urlsafe_b64encode(secret).decode().rstrip("="),
            "companions": [companion.model_dump(mode="json")],
        },
    )


async def record_provider(
    provider: str, *, client: Optional[httpx.AsyncClient] = None, root: Path = FIXTURE_ROOT
) -> RecordRun:
    run = RecordRun(provider=provider)
    recorder = RECORDERS.get(provider)
    if recorder is None:
        run.failures.append(f"no recorder for {provider}")
        return run
    keyring = CorrelationKeyring(signing_key_id="cert", keys={"cert": secrets.token_bytes(32)})
    issued = issue_correlation_token(
        tenant_id=CERTIFICATION_TENANT, key_id="cert", secret=keyring.secret("cert"),
    )
    companion = _task_companion(issued.token, issued.task_ref, issued.issued_at)
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        recordings = await recorder(client, RecordingContext(token=issued.token, task_ref=issued.task_ref))
    except RecorderSkipped as exc:
        run.skipped = str(exc)
        return run
    except (RecorderError, httpx.HTTPError) as exc:
        run.failures.append(f"{provider}: {type(exc).__name__}: {exc}")
        return run
    finally:
        if owns_client:
            await client.aclose()
    if not recordings:
        run.failures.append(f"{provider}: the sandbox returned no records to certify")
    recorded_at = datetime.now(timezone.utc).replace(microsecond=0)
    for recording in recordings:
        try:
            fixture = await fixture_from_recording(recording, keyring=keyring, companion=companion, recorded_at=recorded_at)
        except Exception as exc:  # noqa: BLE001 - a mapper or scrub failure on a real payload is the finding
            run.failures.append(f"{recording.provider}/{recording.kind} ({recording.recorder}): {exc}")
            continue
        run.written.append(str(write_fixture(fixture, root)))
    return run
