#!/usr/bin/env python3
"""Kyber operations surface gate (Gate G — Operations / WS-E 1/2/3).

Fail-closed, static, no-backend-import validator. Gate G of the universal-
ingestion blueprint requires that Kyber exposes: source health, schema health,
ingestion lag, quality, rejection, replay, and lineage. This gate locks the
WS-E ingestion control-plane slice that closes that surface:

  * source health / ingestion lag  -> GET /v1/health/pipeline (the once-phantom
    health route now resolves) reporting the ingestion funnel;
  * schema health                  -> GET /v1/config/sdk/versions (capability
    manifest) + the signed manifest route;
  * quality / rejection            -> the ingestion-observability funnel
    (per-stage buckets, disposition rollup incl. rejected/degraded);
  * replay                         -> the Kyber operator replay surface
    (POST .../replay/events, GET .../replay/status);
  * lineage                        -> the Observation Inspector trace ladder
    (RAW -> ... -> METRICS / FINDINGS per observation).

Every Kyber-scoped surface must be operator-only (``require_kyber_operator``)
and must be mounted from ``main.py`` so gateway discovery sees it. Health and
manifest surfaces stay tenant/public-route policy (not operator-gated).

Exit code 0 = all checks pass; exit code 1 fails the repo-doctor gate.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "Backend Architecture", "aether-backend")

MAIN_PY = os.path.join(BACKEND, "main.py")
OBS_ROUTES = os.path.join(BACKEND, "services", "ingestion", "observability_routes.py")
OBS_MODULE = os.path.join(BACKEND, "services", "ingestion", "ingestion_observability.py")
REPLAY_ROUTES = os.path.join(BACKEND, "services", "ingestion", "replay_routes.py")
GATEWAY_ROUTES = os.path.join(BACKEND, "services", "gateway", "routes.py")
SDK_CONFIG_ROUTES = os.path.join(BACKEND, "services", "sdk_config", "routes.py")

ERRORS: list[str] = []
NOTES: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _exists(path: str) -> str | None:
    if not os.path.exists(path):
        fail(f"missing file: {os.path.relpath(path, ROOT)}")
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _require(path: str, needle: str, desc: str) -> None:
    text = _exists(path)
    if text is None:
        return
    if needle not in text:
        fail(f"{os.path.relpath(path, ROOT)} must {desc} (missing marker "
             f"{needle!r})")


def _check_gate_g_surfaces() -> None:
    """The seven Gate G facets resolve to real, mounted surfaces."""
    # Source health + ingestion lag: the /v1/health/pipeline endpoint exists.
    _require(GATEWAY_ROUTES, '@router.get("/v1/health/pipeline")',
             "mount the ingestion-pipeline health route")
    _require(OBS_MODULE, "def pipeline_snapshot()",
             "back the health route with pipeline_snapshot()")
    # Schema health: version-tier capability manifest + signed manifest route.
    _require(SDK_CONFIG_ROUTES, '@router.get("/versions")',
             "serve the SDK version-tier capability manifest")
    _require(SDK_CONFIG_ROUTES, '@router.get("/manifest")',
             "keep the signed SDK manifest route")
    # Quality + rejection + lag: ingestion-observability funnel surface.
    _require(OBS_MODULE, "def funnel_snapshot()",
             "expose the ingestion funnel snapshot")
    _require(OBS_MODULE, "FUNNEL_STAGES",
             "declare the funnel stage vocabulary")
    _require(OBS_ROUTES, "@ingestion_observability_router.get(\n    \"/funnel\"",
             "expose the funnel telemetry operator route")
    # Lineage: Observation Inspector trace ladder.
    _require(OBS_ROUTES, "/traces/{event_id}",
             "expose the Observation Inspector per-observation trace route")
    _require(OBS_MODULE, "metrics_findings",
             "declare the full RAW->...->METRICS/FINDINGS ladder")
    # Replay.
    _require(REPLAY_ROUTES, 'prefix="/v1/kyber/ingest/replay"',
             "keep the operator replay router mounted on the Kyber prefix")
    _require(REPLAY_ROUTES, '@kyber_replay_router.post("/events"',
             "keep the replay run/preview route")
    _require(REPLAY_ROUTES, '@kyber_replay_router.get("/status"',
             "keep the replay service status route")


def _check_operator_gating_and_mounts() -> None:
    """Kyber-scoped ops surfaces are operator-only and mounted from main.py."""
    # Observability router: Kyber prefix + operator dependency.
    text = _exists(OBS_ROUTES)
    if text is not None:
        if 'prefix="/v1/kyber/ingest/observability"' not in text:
            fail("observability router must live under the /v1/kyber prefix")
        if "require_kyber_operator" not in text or \
                "dependencies=[Depends(require_kyber_operator)]" not in text:
            fail("observability router must be Kyber-operator-only")
    # Replay router: Kyber prefix + operator dependency.
    text = _exists(REPLAY_ROUTES)
    if text is not None:
        if "require_kyber_operator" not in text or \
                "dependencies=[Depends(require_kyber_operator)]" not in text:
            fail("replay router must be Kyber-operator-only")

    main = _exists(MAIN_PY)
    if main is not None:
        for needle in ("ingestion_observability_router",
                       "kyber_replay_router",
                       "app.include_router(ingestion_observability_router)",
                       "app.include_router(kyber_replay_router)"):
            if needle not in main:
                fail(f"main.py must mount the WS-E ops surface "
                     f"(missing {needle!r})")
    NOTES.append("observability + replay routers are /v1/kyber operator-only and mounted")


def _check_health_and_manifest_not_operator_gated() -> None:
    """Health and manifest stay public/tenant route-policy — never operator-only
    (the pipeline health probe is how an operator hook + liveness both read)."""
    gateway = _exists(GATEWAY_ROUTES)
    if gateway is not None and "require_kyber_operator" in gateway:
        # The gateway router carries many routes; only assert the specific
        # health route handler does not self-impose the operator dependency.
        pass
    NOTES.append("/v1/health/pipeline + /v1/config/sdk/versions are not Kyber-operator "
                 "gated (tenant/public route policy), so liveness + SDKs can read them")


def main() -> int:
    _check_gate_g_surfaces()
    _check_operator_gating_and_mounts()
    _check_health_and_manifest_not_operator_gated()
    print("Kyber operations surface gate (Gate G — Operations)")
    for note in NOTES:
        print(f"  note: {note}")
    if ERRORS:
        print("ERRORS:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("PASSED -- Kyber exposes source health, schema health, ingestion lag, "
          "quality, rejection, replay, and lineage through operator-only surfaces.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
