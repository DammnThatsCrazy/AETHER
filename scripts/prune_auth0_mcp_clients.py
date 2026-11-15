#!/usr/bin/env python3
"""Prune stale self-registered MCP clients from an Auth0 tenant.

With ``enable_access_mcp_dcr`` on, any MCP host can register a third-party
client. Registrations that never sign a user in, or stop doing so, are pure
attack surface. This script lists third-party clients (``is_first_party`` is
false), keeps any client named in ``--keep``, and treats a client as stale when
the tenant log holds no successful login (``s``) or token exchange (``seacft``,
``seccft``, ``sertft``) for it within ``--max-idle-days``. Auth0 keeps logs for
a plan-dependent window; a client with no event inside that window is stale.

It is a dry run unless ``--apply`` is passed. It never touches first-party
clients (the Aether SPA, CLI, Kyber or M2M deploy clients).

Credentials come from the environment, as for Terraform: ``AUTH0_DOMAIN``,
``AUTH0_CLIENT_ID`` and ``AUTH0_CLIENT_SECRET`` of a Management API client with
``read:clients``, ``read:logs`` and (for ``--apply``) ``delete:clients``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

SUCCESS_EVENT_TYPES = ("s", "seacft", "seccft", "sertft")
HttpCall = Callable[[str, str, Optional[dict], dict], Any]


@dataclass(frozen=True)
class Decision:
    client_id: str
    name: str
    last_success: Optional[str]
    stale: bool


def _http(method: str, url: str, body: Optional[dict], headers: dict) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "content-type": "application/json", **headers,
    })
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed Auth0 domain
        raw = response.read()
    return json.loads(raw) if raw else None


class Auth0:
    def __init__(self, domain: str, client_id: str, client_secret: str, http: HttpCall = _http):
        if not domain or "/" in domain or not client_id or not client_secret:
            raise ValueError("AUTH0_DOMAIN, AUTH0_CLIENT_ID and AUTH0_CLIENT_SECRET are required")
        self._base = f"https://{domain}"
        self._http = http
        token = http("POST", f"{self._base}/oauth/token", {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": f"{self._base}/api/v2/",
        }, {})
        self._auth = {"authorization": f"Bearer {token['access_token']}"}

    def _get(self, path: str, query: dict) -> Any:
        return self._http("GET", f"{self._base}{path}?{urllib.parse.urlencode(query)}", None, self._auth)

    def third_party_clients(self) -> list[dict]:
        clients: list[dict] = []
        page = 0
        while True:
            batch = self._get("/api/v2/clients", {
                "is_first_party": "false", "fields": "client_id,name,is_first_party",
                "include_fields": "true", "per_page": 50, "page": page,
            }) or []
            clients.extend(c for c in batch if c.get("is_first_party") is False)
            if len(batch) < 50:
                return clients
            page += 1

    def last_success(self, client_id: str) -> Optional[str]:
        types = " OR ".join(f'type:"{t}"' for t in SUCCESS_EVENT_TYPES)
        rows = self._get("/api/v2/logs", {
            "q": f'client_id:"{client_id}" AND ({types})',
            "sort": "date:-1", "per_page": 1, "fields": "date", "include_fields": "true",
        }) or []
        return rows[0].get("date") if rows else None

    def delete_client(self, client_id: str) -> None:
        self._http("DELETE", f"{self._base}/api/v2/clients/{urllib.parse.quote(client_id)}", None, self._auth)


def decide(auth0: Auth0, *, keep: set[str], max_idle_days: int, now: datetime) -> list[Decision]:
    cutoff = now - timedelta(days=max_idle_days)
    decisions: list[Decision] = []
    for client in auth0.third_party_clients():
        client_id = str(client.get("client_id") or "")
        if not client_id or client_id in keep:
            continue
        last = auth0.last_success(client_id)
        try:
            last_at = datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        except ValueError:
            last_at = None
        decisions.append(Decision(
            client_id=client_id,
            name=str(client.get("name") or ""),
            last_success=last,
            stale=last_at is None or last_at < cutoff,
        ))
    return decisions


def main(argv: Optional[list[str]] = None, *, http: HttpCall = _http, now: Optional[datetime] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-idle-days", type=int, default=30)
    parser.add_argument("--keep", action="append", default=[], help="client_id to never prune (repeatable)")
    parser.add_argument("--apply", action="store_true", help="delete stale clients (default: dry run)")
    args = parser.parse_args(argv)
    if args.max_idle_days < 1:
        parser.error("--max-idle-days must be at least 1")
    try:
        auth0 = Auth0(os.environ.get("AUTH0_DOMAIN", ""), os.environ.get("AUTH0_CLIENT_ID", ""),
                      os.environ.get("AUTH0_CLIENT_SECRET", ""), http)
        decisions = decide(auth0, keep=set(args.keep), max_idle_days=args.max_idle_days,
                           now=now or datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - report and fail closed
        print(f"::error::could not evaluate MCP clients: {type(exc).__name__}", file=sys.stderr)
        return 1
    stale = [d for d in decisions if d.stale]
    for d in decisions:
        print(json.dumps({"client_id": d.client_id, "name": d.name, "last_success": d.last_success,
                          "stale": d.stale, "action": ("delete" if d.stale and args.apply else
                                                       "would_delete" if d.stale else "keep")}))
    if args.apply:
        for d in stale:
            auth0.delete_client(d.client_id)
    print(f"third_party_clients={len(decisions)} stale={len(stale)} applied={args.apply}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
