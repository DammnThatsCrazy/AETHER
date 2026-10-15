"""Mark Neptune chain and card catalog vertices as ``platform`` owned.

Graph writes never change a vertex's owner and tenant writers may not write
``platform`` vertices, so the platform writers of these reference vertices
(asset registry seeds, card catalog) fail with ``VertexOwnershipError`` while a
vertex still carries an older owner. ``repositories.tenant_row_keys`` fixes the
PostgreSQL graph backend; this module does the same for Neptune.

Vertices are selected by label, then by id prefix, so tenant-prefixed chain
vertices (``{tenant}:chain:...``) keep their tenant. Without ``--apply`` it
only prints what it would change::

    NEPTUNE_ENDPOINT=... python -m graph.platform_vertex_owners           # dry run
    NEPTUNE_ENDPOINT=... python -m graph.platform_vertex_owners --apply
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Iterable

from repositories.tenant_row_keys import PLATFORM_VERTEX_PREFIXES

LABELS = ("Chain", "CardProgram", "CardIssuer", "PaymentNetwork")
PLATFORM = "platform"
_TENANT_KEYS = ("tenantId", "tenant_id")


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def to_relabel(vertices: Iterable[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """``(vertex id, tenant properties)`` of catalog vertices not yet platform owned."""
    pending = []
    for vertex_id, properties in vertices:
        if not str(vertex_id).startswith(PLATFORM_VERTEX_PREFIXES):
            continue
        owners = {key: _first(properties.get(key)) for key in _TENANT_KEYS}
        if any(owner != PLATFORM for owner in owners.values()):
            pending.append((str(vertex_id), owners))
    return pending


def relabel(g: Any, apply: bool) -> list[tuple[str, dict]]:
    """Find (and with ``apply``, fix) catalog vertices on traversal source ``g``."""
    from gremlin_python.process.traversal import Cardinality, T

    rows = g.V().hasLabel(*LABELS).valueMap(True, *_TENANT_KEYS).toList()
    pending = to_relabel((row[T.id], row) for row in rows)
    if apply:
        for vertex_id, _ in pending:
            (
                g.V(vertex_id)
                .property(Cardinality.single, "tenantId", PLATFORM)
                .property(Cardinality.single, "tenant_id", PLATFORM)
                .iterate()
            )
    return pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", default=os.getenv("NEPTUNE_ENDPOINT", ""))
    parser.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    args = parser.parse_args(argv)
    if not args.endpoint:
        parser.error("--endpoint or NEPTUNE_ENDPOINT is required")

    from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
    from gremlin_python.process.anonymous_traversal import traversal

    connection = DriverRemoteConnection(f"wss://{args.endpoint}:8182/gremlin", "g")
    try:
        pending = relabel(traversal().withRemote(connection), args.apply)
    finally:
        connection.close()
    verb = "relabelled" if args.apply else "would relabel"
    for vertex_id, owners in pending:
        print(f"{verb} {vertex_id} (was {owners})")
    print(f"{verb} {len(pending)} vertices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
