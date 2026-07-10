"""Redis check for the staging preflight gate.

``redis:ping`` — connect with redis.asyncio using the candidate env's
REDIS_URL (or a URL built from REDIS_HOST/REDIS_PORT/REDIS_DB/REDIS_PASSWORD,
mirroring config/settings.py::RedisConfig.url) and issue PING.

SKIPs in ``--dry-run`` (no live services are touched).
"""

from __future__ import annotations

from .preflight_results import CheckResult, failed, passed, skipped

CHECK_NAME = "redis:ping"


def resolve_redis_url(env: dict) -> str:
    """REDIS_URL wins; otherwise build from REDIS_HOST/PORT/DB/PASSWORD
    exactly as config/settings.py::RedisConfig.url does. Empty string when
    no Redis configuration is present."""
    url = env.get("REDIS_URL", "").strip()
    if url:
        return url
    host = env.get("REDIS_HOST", "").strip()
    if not host:
        return ""
    port = env.get("REDIS_PORT", "6379").strip() or "6379"
    db = env.get("REDIS_DB", "0").strip() or "0"
    password = env.get("REDIS_PASSWORD", "")
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


async def run_redis_checks(env: dict, *, dry_run: bool = False) -> list[CheckResult]:
    if dry_run:
        return [skipped(CHECK_NAME, "dry-run: live Redis checks are not executed")]

    url = resolve_redis_url(env)
    if not url:
        return [failed(
            CHECK_NAME,
            "no REDIS_URL or REDIS_HOST in the candidate environment",
            "set REDIS_URL or REDIS_HOST/REDIS_PORT for the staging Redis",
        )]

    try:
        import redis.asyncio as aioredis
    except ImportError as exc:
        return [failed(
            CHECK_NAME,
            f"redis package is not installed: {exc}",
            "pip install -e '.[backend]' (or pip install redis)",
        )]

    client = aioredis.from_url(url, socket_connect_timeout=10, socket_timeout=10)
    try:
        pong = await client.ping()
    except Exception as exc:
        return [failed(
            CHECK_NAME,
            f"PING failed: {exc}",
            "verify Redis is reachable from this host and credentials are correct",
        )]
    finally:
        close = getattr(client, "aclose", None) or client.close
        try:
            await close()
        except Exception:
            pass

    if pong:
        return [passed(CHECK_NAME, "PING returned PONG")]
    return [failed(
        CHECK_NAME,
        f"PING returned {pong!r}",
        "verify the Redis endpoint is a real Redis server",
    )]
