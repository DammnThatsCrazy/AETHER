"""Live HTTP checks for the staging preflight gate.

Only run when ``--base-url`` is provided:

- ``http:health`` GET {base}/v1/health must return 200 with no failing
  dependency (the gateway deep probe reports ``status`` plus a
  ``dependencies`` map — see services/gateway/routes.py).
- ``http:ready``  GET {base}/v1/ready must return 200.

Both SKIP without ``--base-url`` and in ``--dry-run``.
"""

from __future__ import annotations

from typing import Optional

from .preflight_results import CheckResult, failed, passed, skipped

CHECK_NAMES = ("http:health", "http:ready")


def _health_result(status_code: int, payload: object) -> CheckResult:
    name = "http:health"
    if status_code != 200:
        return failed(
            name,
            f"GET /v1/health returned HTTP {status_code}",
            "inspect backend logs; the deep health probe must return 200",
        )
    if not isinstance(payload, dict):
        return failed(
            name,
            "GET /v1/health returned 200 but the body is not a JSON object",
            "verify the deployment serves the Aether gateway health route",
        )
    dependencies = payload.get("dependencies", {})
    failing = sorted(
        dep for dep, state in dependencies.items()
        if isinstance(state, dict) and state.get("status") != "ok"
    ) if isinstance(dependencies, dict) else []
    overall = payload.get("status")
    if failing or overall == "degraded":
        detail = f"health status={overall!r}"
        if failing:
            detail += f"; failing dependencies: {', '.join(failing)}"
        return failed(
            name,
            detail,
            "bring the failing dependencies back to healthy before promoting",
        )
    dep_count = len(dependencies) if isinstance(dependencies, dict) else 0
    return passed(name, f"status={overall!r}; {dep_count} dependencies ok")


async def run_http_checks(
    base_url: Optional[str],
    *,
    dry_run: bool = False,
) -> list[CheckResult]:
    if dry_run:
        return [
            skipped(name, "dry-run: live HTTP checks are not executed")
            for name in CHECK_NAMES
        ]
    if not base_url:
        return [
            skipped(name, "no --base-url provided")
            for name in CHECK_NAMES
        ]

    try:
        import httpx
    except ImportError as exc:
        return [
            failed(
                name,
                f"httpx is not installed: {exc}",
                "pip install -e '.[backend]' (or pip install httpx)",
            )
            for name in CHECK_NAMES
        ]

    base = base_url.rstrip("/")
    results: list[CheckResult] = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        # -- http:health -----------------------------------------------------
        try:
            resp = await client.get(f"{base}/v1/health")
        except Exception as exc:
            results.append(failed(
                "http:health",
                f"GET /v1/health failed: {exc}",
                "verify the base URL and that the backend is reachable",
            ))
        else:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            results.append(_health_result(resp.status_code, payload))

        # -- http:ready ------------------------------------------------------
        try:
            resp = await client.get(f"{base}/v1/ready")
        except Exception as exc:
            results.append(failed(
                "http:ready",
                f"GET /v1/ready failed: {exc}",
                "verify the base URL and that the backend is reachable",
            ))
        else:
            if resp.status_code == 200:
                results.append(passed("http:ready", "GET /v1/ready returned 200"))
            else:
                results.append(failed(
                    "http:ready",
                    f"GET /v1/ready returned HTTP {resp.status_code}",
                    "the readiness probe must return 200 before traffic is routed",
                ))
    return results
