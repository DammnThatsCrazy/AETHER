"""
Aether Backend — Dependency Injection
Centralized resource providers using FastAPI Depends.
Eliminates module-level singletons — each resource has a single lifecycle.
"""

from __future__ import annotations

from typing import Any, Optional

from config.settings import settings
from shared.cache.cache import CacheClient
from shared.events.events import EventProducer, EventConsumer
from shared.graph.graph import GraphClient
from shared.rate_limit.limiter import BurstRateLimiter
from shared.rate_limit.quota import QuotaEngine
from shared.rate_limit.quota_flush import QuotaFlusher
from shared.rate_limit.feature_gate import FeatureGate
from shared.auth.auth import JWTHandler, APIKeyValidator
from shared.logger.logger import get_logger
from shared.providers.key_vault import BYOKKeyVault
from shared.providers.meter import UsageMeter
from shared.providers.registry import ProviderRegistry
from shared.providers.router import AdaptiveRouter

logger = get_logger("aether.dependencies")


class ResourceRegistry:
    """
    Singleton registry that owns the lifecycle of all shared resources.
    Created at app startup, torn down at shutdown.
    """

    def __init__(self) -> None:
        self.cache = CacheClient()
        self.graph = GraphClient()
        self.producer = EventProducer()
        self.consumer = EventConsumer()
        self.rate_limiter = BurstRateLimiter()
        self.quota_engine = QuotaEngine()
        self.quota_flusher = QuotaFlusher()
        self.feature_gate = FeatureGate()
        self.quota_notifier = None  # Set during startup once notifier available
        self.jwt_handler = JWTHandler()
        self.api_key_validator = APIKeyValidator()
        self._started = False

    async def startup(self) -> None:
        """Initialize all connections. Called from FastAPI lifespan."""
        logger.info("Initializing shared resources...")
        await self.cache.connect()
        await self.graph.connect()
        await self.producer.connect()
        await self.rate_limiter.connect()
        await self.quota_engine.connect()
        # Share Redis client with the quota flusher
        if self.quota_engine._redis is not None:
            self.quota_flusher.set_redis(self.quota_engine._redis)
        # Inject cache into API key validator for async lookups
        self.api_key_validator._cache = self.cache
        # Initialize database connection pool
        try:
            from repositories.repos import get_pool
            pool = await get_pool()
            if pool is not None:
                from shared.billing.migrations import ensure_billing_tables
                await ensure_billing_tables(pool)
        except Exception as e:
            logger.warning(f"Database pool initialization: {e}")
        # Wire the quota notifier (best-effort)
        try:
            from shared.billing.notifications import QuotaNotifier
            self.quota_notifier = QuotaNotifier(
                redis_client=self.quota_engine._redis,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.debug(f"QuotaNotifier setup skipped: {e}")
        # Start the periodic quota flusher
        try:
            self.quota_flusher.start(
                interval_s=settings.rate_limit.quota_flush_interval_s,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.debug(f"QuotaFlusher start skipped: {e}")
        self._started = True
        logger.info("All shared resources initialized")

    async def shutdown(self) -> None:
        """Gracefully close all connections."""
        logger.info("Shutting down shared resources...")
        try:
            self.quota_flusher.stop()
        except Exception:
            pass
        await self.producer.close()
        await self.graph.close()
        await self.cache.close()
        try:
            from repositories.repos import close_pool
            await close_pool()
        except Exception:
            pass
        self._started = False
        logger.info("All shared resources closed")

    async def health_check(self) -> dict[str, Any]:
        """Probe all dependencies and return status map."""
        checks: dict[str, Any] = {}

        # Check database
        try:
            from repositories.repos import get_pool
            pool = await get_pool()
            if pool:
                await pool.fetchval("SELECT 1")
                checks["database"] = {"status": "ok", "backend": "postgresql"}
            else:
                checks["database"] = {"status": "ok", "backend": "in-memory"}
        except Exception as e:
            checks["database"] = {"status": "error", "error": str(e)}

        for name, check_fn in [
            ("cache", self.cache.health_check),
            ("graph", self.graph.health_check),
            ("event_bus", self.producer.health_check),
        ]:
            try:
                healthy = await check_fn()
                checks[name] = {"status": "ok" if healthy else "degraded"}
            except Exception as e:
                checks[name] = {"status": "error", "error": str(e)}
        return checks


# Module-level singleton — initialized once, used everywhere via FastAPI Depends
_registry: Optional[ResourceRegistry] = None


def get_registry() -> ResourceRegistry:
    """Get or create the global resource registry."""
    global _registry
    if _registry is None:
        _registry = ResourceRegistry()
    return _registry


# ── FastAPI dependency functions ────────────────────────────────────────

def get_cache() -> CacheClient:
    return get_registry().cache


def get_graph() -> GraphClient:
    return get_registry().graph


def get_producer() -> EventProducer:
    return get_registry().producer


def get_consumer() -> EventConsumer:
    return get_registry().consumer


def get_rate_limiter() -> BurstRateLimiter:
    return get_registry().rate_limiter


def get_quota_engine() -> QuotaEngine:
    return get_registry().quota_engine


def get_feature_gate() -> FeatureGate:
    return get_registry().feature_gate


def get_jwt_handler() -> JWTHandler:
    return get_registry().jwt_handler


def get_api_key_validator() -> APIKeyValidator:
    return get_registry().api_key_validator


# ── Provider Gateway ──────────────────────────────────────────────────

class ProviderGateway:
    """
    Facade that owns the BYOK key vault, provider registry,
    usage meter, and adaptive router.
    """

    def __init__(self) -> None:
        gw_cfg = settings.provider_gateway
        self.key_vault = BYOKKeyVault(encryption_key=gw_cfg.encryption_key or "dev-key")
        self.meter = UsageMeter(flush_interval_s=gw_cfg.meter_flush_interval_s)
        self.registry = ProviderRegistry(key_vault=self.key_vault)
        self.router = AdaptiveRouter(
            registry=self.registry,
            meter=self.meter,
            max_retries=gw_cfg.max_retries,
        )
        self._started = False

    async def startup(self) -> None:
        """Bootstrap system-default providers from env vars."""
        await self.registry.initialize_system_providers(settings)
        self._started = True
        logger.info("ProviderGateway started")

    async def shutdown(self) -> None:
        """Tear down all provider instances and flush metering."""
        await self.meter.flush()
        await self.registry.teardown()
        self._started = False
        logger.info("ProviderGateway shut down")

    async def route(self, **kwargs):
        """Delegate to AdaptiveRouter.route()."""
        return await self.router.route(**kwargs)

    async def health_check(self) -> dict:
        return await self.router.health()


_provider_gateway: Optional[ProviderGateway] = None


def get_provider_gateway() -> Optional[ProviderGateway]:
    """Get the Provider Gateway instance (None if feature disabled)."""
    return _provider_gateway


def _init_provider_gateway() -> Optional[ProviderGateway]:
    """Create the ProviderGateway singleton if enabled."""
    global _provider_gateway
    if settings.provider_gateway.enabled and _provider_gateway is None:
        _provider_gateway = ProviderGateway()
    return _provider_gateway
