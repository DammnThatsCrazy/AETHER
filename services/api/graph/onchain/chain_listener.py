"""
Aether Service — Chain Listener

Listens to on-chain events via WebSocket streams (QuickNode/Alchemy)
and routes to ActionRecorder for persistence and graph mutations.

Production features:
- Automatic reconnection with exponential backoff
- Health/readiness reporting
- Per-stream metrics
- Clean shutdown
- Configuration-driven stream management
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Optional

from shared.logger.logger import get_logger, metrics

from .models import ChainListenerConfig

logger = get_logger("aether.service.onchain.listener")

# Optional websockets import
try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    websockets = None  # type: ignore[assignment]
    WS_AVAILABLE = False


class ChainListener:
    """
    Listens to blockchain events via configurable WebSocket streams.

    Production: connects to QuickNode Streams or Alchemy WebSocket endpoints.
    Local: runs in configuration-only mode (no WebSocket connection) when
    QUICKNODE_ENDPOINT is not set.
    """

    MAX_RECONNECT_DELAY = 60  # seconds
    INITIAL_RECONNECT_DELAY = 1  # seconds

    def __init__(self, on_event: Optional[Callable] = None) -> None:
        self._configs: dict[str, ChainListenerConfig] = {}
        self._running = False
        self._tasks: dict[str, asyncio.Task] = {}
        self._on_event = on_event
        self._reconnect_counts: dict[str, int] = {}
        self._last_event_times: dict[str, float] = {}

    async def configure(self, config: ChainListenerConfig) -> ChainListenerConfig:
        """Add or update a chain listener configuration."""
        if not config.config_id:
            config.config_id = f"{config.chain_id}_{config.vm_type}"

        self._configs[config.config_id] = config
        metrics.increment("chain_listener_configured", labels={"chain_id": config.chain_id})
        logger.info(
            f"Chain listener configured: {config.config_id} "
            f"(chain={config.chain_id}, filters={len(config.filter_addresses)} addresses)"
        )
        return config

    async def start(self) -> None:
        """Start all configured listeners as background tasks."""
        self._running = True
        for config_id, config in self._configs.items():
            if config.enabled:
                task = asyncio.create_task(self._listen_loop(config_id, config))
                self._tasks[config_id] = task
                logger.info(f"Chain listener started: {config_id}")
        logger.info(f"Chain listener running with {len(self._tasks)} active streams")
        metrics.increment("chain_listener_started")

    async def stop(self) -> None:
        """Stop all listeners gracefully."""
        self._running = False
        for config_id, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Chain listener stopped: {config_id}")
        self._tasks.clear()
        logger.info("All chain listeners stopped")
        metrics.increment("chain_listener_stopped")

    async def _listen_loop(self, config_id: str, config: ChainListenerConfig) -> None:
        """Main listen loop with reconnection and backoff."""
        delay = self.INITIAL_RECONNECT_DELAY
        self._reconnect_counts[config_id] = 0

        while self._running:
            endpoint = config.endpoint or os.getenv("QUICKNODE_ENDPOINT", "")
            if not endpoint:
                logger.warning(f"Chain listener {config_id}: no endpoint configured, waiting...")
                metrics.increment("chain_listener_no_endpoint", labels={"config_id": config_id})
                await asyncio.sleep(30)
                continue

            if not WS_AVAILABLE:
                logger.warning(f"Chain listener {config_id}: websockets not installed, polling mode only")
                await asyncio.sleep(60)
                continue

            try:
                logger.info(f"Chain listener {config_id}: connecting to {endpoint[:50]}...")
                async with websockets.connect(endpoint, ping_interval=30, ping_timeout=10) as ws:
                    delay = self.INITIAL_RECONNECT_DELAY  # Reset on successful connect
                    self._reconnect_counts[config_id] = 0
                    metrics.increment("chain_listener_connected", labels={"config_id": config_id})
                    logger.info(f"Chain listener {config_id}: connected")

                    # Subscribe to configured filters
                    if config.filter_addresses:
                        sub_msg = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "eth_subscribe",
                            "params": ["logs", {"address": config.filter_addresses}],
                        }
                        import json
                        await ws.send(json.dumps(sub_msg))

                    # Listen for events
                    async for message in ws:
                        self._last_event_times[config_id] = time.time()
                        metrics.increment("chain_listener_events", labels={
                            "config_id": config_id, "chain_id": config.chain_id,
                        })

                        if self._on_event:
                            try:
                                import json
                                event_data = json.loads(message)
                                await self._on_event(config, event_data)
                            except Exception as e:
                                logger.error(f"Chain listener {config_id}: event handler error: {e}")
                                metrics.increment("chain_listener_handler_error", labels={"config_id": config_id})

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._reconnect_counts[config_id] = self._reconnect_counts.get(config_id, 0) + 1
                logger.warning(
                    f"Chain listener {config_id}: disconnected ({e}), "
                    f"reconnecting in {delay}s (attempt {self._reconnect_counts[config_id]})"
                )
                metrics.increment("chain_listener_reconnect", labels={"config_id": config_id})
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_RECONNECT_DELAY)

    def get_configs(self) -> list[ChainListenerConfig]:
        """Return all listener configurations."""
        return list(self._configs.values())

    @property
    def is_running(self) -> bool:
        return self._running

    def health(self) -> dict:
        """Return health status of all listeners."""
        now = time.time()
        streams = {}
        for config_id, config in self._configs.items():
            last_event = self._last_event_times.get(config_id)
            reconnects = self._reconnect_counts.get(config_id, 0)
            streams[config_id] = {
                "enabled": config.enabled,
                "running": config_id in self._tasks,
                "reconnect_count": reconnects,
                "last_event_age_seconds": round(now - last_event, 1) if last_event else None,
                "status": "healthy" if config_id in self._tasks and reconnects < 3 else "degraded",
            }
        return {
            "running": self._running,
            "stream_count": len(self._tasks),
            "streams": streams,
        }
