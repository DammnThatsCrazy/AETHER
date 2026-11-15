#!/usr/bin/env python3
"""Certify agent correlation mappers against provider sandboxes.

    python scripts/certify_agent_correlation.py record --provider stripe [--provider shopify ...]
    python scripts/certify_agent_correlation.py replay            # rewrite the report from fixtures
    python scripts/certify_agent_correlation.py replay --check    # fail on a failing fixture or stale report

``record`` creates test activity in each named sandbox (Stripe test mode only;
Shopify draft products, deleted afterwards; Ramp and Cloudflare read-only),
reads back the provider's own records, and writes scrubbed fixtures under
``services/api/tests/agent_correlation/fixtures/sandbox/``. Credentials come
from the environment (``STRIPE_SANDBOX_SECRET_KEY``, ``SHOPIFY_SANDBOX_SHOP``
and ``SHOPIFY_SANDBOX_ACCESS_TOKEN``, ``RAMP_SANDBOX_CLIENT_ID`` and
``RAMP_SANDBOX_CLIENT_SECRET``, ``CLOUDFLARE_ACCOUNT_ID``,
``CLOUDFLARE_AI_GATEWAY_ID`` and ``CLOUDFLARE_API_TOKEN``, ``OPENAI_API_KEY``)
or from a credential proxy that injects them.

``replay`` maps every fixture again and writes
``config/agent_correlation_certification.json``: a kind is ``sandbox_certified``
only when it has recorded fixtures and all of them replay.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from actions.agent_correlation.certification.record import record_provider  # noqa: E402
from actions.agent_correlation.certification.recorders import RECORDERS  # noqa: E402
from actions.agent_correlation.certification.runner import (  # noqa: E402
    REPORT_PATH,
    build_report,
    render_report,
    replay_all,
)


async def _replay(check: bool) -> int:
    results = await replay_all()
    rendered = render_report(build_report(results))
    failed = [r for r in results if not r.passed]
    for r in failed:
        print(f"FAIL {r.fixture.provider}/{r.fixture.kind} {r.fixture.recorder}: {'; '.join(r.failures)}")
    if check:
        current = REPORT_PATH.read_text() if REPORT_PATH.exists() else ""
        if current != rendered:
            print(f"{REPORT_PATH.relative_to(ROOT)} is stale; run: python scripts/certify_agent_correlation.py replay")
            return 1
    else:
        REPORT_PATH.write_text(rendered)
        print(f"wrote {REPORT_PATH.relative_to(ROOT)} from {len(results)} fixtures")
    return 1 if failed else 0


async def _record(providers: list[str]) -> int:
    status = 0
    for provider in providers:
        run = await record_provider(provider)
        if run.skipped:
            print(f"SKIP {provider}: {run.skipped}")
        for path in run.written:
            print(f"wrote {Path(path).relative_to(ROOT)}")
        for failure in run.failures:
            print(f"FAIL {failure}")
            status = 1
    replay_status = await _replay(check=False)
    return status or replay_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="record sandbox payloads into fixtures")
    rec.add_argument("--provider", action="append", choices=sorted(RECORDERS), required=True)
    rep = sub.add_parser("replay", help="replay fixtures and write the certification report")
    rep.add_argument("--check", action="store_true", help="fail when the committed report is stale")
    args = parser.parse_args()
    if args.command == "record":
        return asyncio.run(_record(args.provider))
    return asyncio.run(_replay(args.check))


if __name__ == "__main__":
    raise SystemExit(main())
