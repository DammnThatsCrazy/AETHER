from __future__ import annotations

import os
from typing import Any

from .service import DemoSeedService


async def maybe_seed_demo_on_start(app: Any, *, environment: str) -> bool:
    """Run only the explicitly requested local/test in-process demo seed."""
    enabled = os.getenv("AETHER_DEMO_SEED_ON_START", "").strip().lower() == "true"
    if not enabled:
        return False
    if environment not in {"local", "test"}:
        raise RuntimeError(
            "AETHER_DEMO_SEED_ON_START is permitted only in local/test"
        )
    tenant_id = os.getenv("AETHER_DEMO_TENANT_ID", "").strip()
    namespace = os.getenv("AETHER_DEMO_SEED_NAMESPACE", "").strip()
    if not tenant_id or not namespace:
        raise RuntimeError(
            "AETHER_DEMO_TENANT_ID and AETHER_DEMO_SEED_NAMESPACE are "
            "required when AETHER_DEMO_SEED_ON_START=true"
        )
    app.state.demo_seed_result = await DemoSeedService(
        environment=environment,
    ).seed(
        tenant_id=tenant_id,
        namespace=namespace,
        actor="explicit-backend-startup",
    )
    return True
